# ==============================================================================
# MÓDULO DE INTEGRACIÓN DE STREAMING DE VOZ DE TWILIO (VishGuard)
# ==============================================================================
# Flujo:
# 1. Twilio llama al webhook POST /twilio/voice.
# 2. Respondemos TwiML: <Start><Stream> (con <Parameter to=...>) + <Dial>.
# 3. Twilio abre el WebSocket /ws/twilio y envía audio mu-law 8 kHz en base64.
# 4. Acumulamos 3 s de audio PCM16 y lo procesamos EN SEGUNDO PLANO:
#    transcripción -> VishingAnalyzer -> notificación a la app -> DB.
#
# Variables de entorno:
#   VISHGUARD_DESTINO   número real que debe sonar (E.164, ej. +502...)  [obligatoria]
#   PUBLIC_URL          URL pública (ej. https://xxxx.ngrok-free.app)    [recomendada]
#   TWILIO_AUTH_TOKEN   si está definida, se valida la firma de Twilio
#   VISHGUARD_STT       simulado (defecto) | groq
#   GROQ_API_KEY        necesaria si VISHGUARD_STT=groq
#   GROQ_STT_MODEL      defecto whisper-large-v3-turbo
#   VISHGUARD_DEBUG     1 para habilitar /debug/connections
#
# Dependencias: python-multipart (request.form), twilio, audioop-lts (Python 3.13+),
# groq (solo si VISHGUARD_STT=groq).
# ==============================================================================

import asyncio
import base64
import binascii
import io
import json
import logging
import os
import wave
from typing import Optional

# audioop es stdlib hasta Python 3.12. En 3.13+: pip install audioop-lts
# (se sigue importando como `audioop`).
import audioop

from fastapi import (
    APIRouter,
    HTTPException,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from twilio.request_validator import RequestValidator
from twilio.twiml.voice_response import Dial, Start, VoiceResponse

from core.alert_service import guardar_alerta_si_aplica
from core.connection_manager import manager
from modules.analyzer import VishingAnalyzer

logger = logging.getLogger("vishguard.twilio")

router = APIRouter()
analyzer = VishingAnalyzer()

# --- Parámetros de audio ------------------------------------------------------
# 8000 Hz x 2 bytes = 16,000 bytes/s  ->  48,000 bytes = 3 s
BYTES_POR_SEGUNDO = 8000 * 2
CHUNK_BYTES = BYTES_POR_SEGUNDO * 3
MIN_REMANENTE_BYTES = BYTES_POR_SEGUNDO // 2   # 0.5 s mínimo al cortar la llamada
UMBRAL_SILENCIO_RMS = 150                      # por debajo se considera silencio

STT_MODE = os.getenv("VISHGUARD_STT", "simulado").lower()

# Referencias fuertes a los análisis en curso: asyncio solo guarda referencias
# débiles a las tareas y podría recolectarlas antes de terminar.
_TAREAS_ACTIVAS: set[asyncio.Task] = set()


def _mask(numero: Optional[str]) -> str:
    return f"***{numero[-4:]}" if numero else "?"


# ==============================================================================
# UTILIDADES DE URL Y SEGURIDAD
# ==============================================================================
def _urls_publicas(request: Request) -> tuple[str, str]:
    """Devuelve (base_http, base_ws). Prefiere PUBLIC_URL; si no, usa el Host."""
    public = os.getenv("PUBLIC_URL", "").rstrip("/")
    if public:
        ws_base = public.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
        return public, ws_base

    host = request.headers.get("host")
    if not host:
        raise HTTPException(status_code=400, detail="Falta la cabecera Host")
    https = "ngrok" in host or request.headers.get("x-forwarded-proto") == "https"
    return (
        f"{'https' if https else 'http'}://{host}",
        f"{'wss' if https else 'ws'}://{host}",
    )


def _validar_firma_twilio(request: Request, http_base: str, form) -> None:
    token = os.getenv("TWILIO_AUTH_TOKEN")
    if not token:
        logger.warning("TWILIO_AUTH_TOKEN no definido: webhook SIN validar firma")
        return
    url = f"{http_base}{request.url.path}"
    if request.url.query:
        url += f"?{request.url.query}"
    firma = request.headers.get("X-Twilio-Signature", "")
    if not RequestValidator(token).validate(url, dict(form), firma):
        raise HTTPException(status_code=403, detail="Firma de Twilio inválida")


# ==============================================================================
# PASO 1: WEBHOOK HTTP - RECEPCIÓN DE LA LLAMADA
# ==============================================================================
@router.post("/twilio/voice")
async def twilio_voice_webhook(request: Request):
    http_base, ws_base = _urls_publicas(request)

    form = await request.form()
    _validar_firma_twilio(request, http_base, form)

    destino = manager.normalizar(os.getenv("VISHGUARD_DESTINO"))
    if not destino:
        logger.error("VISHGUARD_DESTINO no está configurada")
        raise HTTPException(status_code=500, detail="Destino no configurado")

    response = VoiceResponse()

    # Stream del audio entrante (la voz del llamante) sin bloquear la llamada.
    # El número va como <Parameter>, NO en la query string de la URL.
    start = Start()
    stream = start.stream(url=f"{ws_base}/ws/twilio", track="inbound_track")
    stream.parameter(name="to", value=destino)
    response.append(start)

    # answer_on_bridge: Twilio no contesta hasta que el usuario conteste.
    dial = Dial(answer_on_bridge=True)
    dial.number(destino)
    response.append(dial)

    return Response(content=str(response), media_type="application/xml")


# ==============================================================================
# TRANSCRIPCIÓN (bloqueante: se ejecuta en un hilo con asyncio.to_thread)
# ==============================================================================
_groq_client = None


def _get_groq():
    global _groq_client
    if _groq_client is None:
        from groq import Groq

        _groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    return _groq_client


def _a_wav_16k(pcm8k: bytes) -> bytes:
    """PCM16 8 kHz mono -> WAV 16 kHz mono (lo que Whisper espera)."""
    pcm16k, _ = audioop.ratecv(pcm8k, 2, 1, 8000, 16000, None)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(pcm16k)
    return buf.getvalue()


def transcribir_audio(pcm8k: bytes) -> str:
    if STT_MODE == "simulado":
        return "Simulación: Necesitamos confirmación de su clave bancaria por seguridad urgente."

    # Silencio: no gastar una llamada a la API
    if audioop.rms(pcm8k, 2) < UMBRAL_SILENCIO_RMS:
        return ""

    if STT_MODE == "groq":
        resultado = _get_groq().audio.transcriptions.create(
            file=("audio.wav", _a_wav_16k(pcm8k)),
            model=os.getenv("GROQ_STT_MODEL", "whisper-large-v3-turbo"),
            language="es",
            response_format="text",
        )
        texto = resultado if isinstance(resultado, str) else getattr(resultado, "text", "")
        return (texto or "").strip()

    logger.error("VISHGUARD_STT desconocido: %s", STT_MODE)
    return ""


# ==============================================================================
# CANALIZACIÓN DE ANÁLISIS (corre en segundo plano, sin frenar el audio)
# ==============================================================================
async def _procesar_chunk(pcm: bytes, destino: Optional[str], lock: asyncio.Lock):
    # El lock mantiene el orden de los resultados dentro de una misma llamada.
    async with lock:
        try:
            texto = await asyncio.to_thread(transcribir_audio, pcm)
            if not texto:
                return

            resultado = await asyncio.to_thread(analyzer.analizar_texto, texto)
            logger.info(
                "[VishGuard] riesgo=%s score=%s",
                resultado.get("nivel_riesgo"),
                resultado.get("score"),
            )

            if destino:
                await manager.enviar_a(destino, resultado)

            # Con STT simulado NO se guarda en la DB (evita alertas falsas).
            if STT_MODE != "simulado":
                await asyncio.to_thread(guardar_alerta_si_aplica, resultado)
        except Exception:
            logger.exception("Error procesando chunk de audio")


# ==============================================================================
# PASO 2: WEBSOCKET - PROCESAMIENTO DE AUDIO EN TIEMPO REAL
# ==============================================================================
@router.websocket("/ws/twilio")
async def twilio_websocket_endpoint(websocket: WebSocket, to: Optional[str] = None):
    """Twilio transmite aquí el audio de la llamada en eventos JSON.

    `to` por query string se mantiene solo como respaldo; el valor normal
    llega en el evento `start` (customParameters).
    """
    await websocket.accept()
    logger.info("Conexión WebSocket establecida con Twilio")

    destino = manager.normalizar(to) or None
    audio_buffer = bytearray()
    lock = asyncio.Lock()
    tareas: set[asyncio.Task] = set()

    def lanzar(pcm: bytes):
        tarea = asyncio.create_task(_procesar_chunk(pcm, destino, lock))
        tareas.add(tarea)
        _TAREAS_ACTIVAS.add(tarea)
        tarea.add_done_callback(tareas.discard)
        tarea.add_done_callback(_TAREAS_ACTIVAS.discard)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            event = data.get("event")

            if event == "start":
                info = data.get("start", {})
                params = info.get("customParameters") or {}
                destino = manager.normalizar(params.get("to")) or destino
                logger.info(
                    "Stream iniciado (callSid=%s, destino=%s)",
                    info.get("callSid"),
                    _mask(destino),
                )

            elif event == "media":
                payload = (data.get("media") or {}).get("payload")
                if not payload:
                    continue
                try:
                    raw_mulaw = base64.b64decode(payload, validate=True)
                except (binascii.Error, ValueError):
                    logger.warning("Payload base64 inválido: se descarta el frame")
                    continue
                # mu-law 8 kHz -> PCM lineal 16 bit
                audio_buffer.extend(audioop.ulaw2lin(raw_mulaw, 2))

                if len(audio_buffer) >= CHUNK_BYTES:
                    lanzar(bytes(audio_buffer))
                    audio_buffer.clear()

            elif event == "stop":
                logger.info("Transmisión finalizada por Twilio")
                if len(audio_buffer) >= MIN_REMANENTE_BYTES:
                    lanzar(bytes(audio_buffer))
                    audio_buffer.clear()
                break

            # "connected", "mark", "dtmf": se ignoran

    except WebSocketDisconnect:
        logger.info("Conexión cerrada abruptamente por Twilio")
    except Exception:
        logger.exception("Error en /ws/twilio")
    finally:
        # Deja terminar los análisis pendientes (incluye el remanente).
        # shield: si el servidor cancela este handler por una desconexión
        # abrupta, los análisis NO se cancelan y terminan en segundo plano.
        if tareas:
            await asyncio.shield(asyncio.gather(*tareas, return_exceptions=True))
        try:
            await websocket.close()
        except Exception:
            pass


# ==============================================================================
# DEBUG (apagado por defecto; sin números completos)
# ==============================================================================
@router.get("/debug/connections")
def ver_conexiones():
    if os.getenv("VISHGUARD_DEBUG", "").lower() not in ("1", "true", "yes"):
        raise HTTPException(status_code=404)
    return {
        "total": len(manager.active_connections),
        "conectados": [_mask(n) for n in manager.active_connections],
    }