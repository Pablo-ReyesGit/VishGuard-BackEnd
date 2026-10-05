# ==============================================================================
# MÓDULO DE INTEGRACIÓN DE STREAMING DE VOZ DE TWILIO (VishGuard)
# ==============================================================================
# Flujo:
# 1. Twilio llama al webhook POST /twilio/voice.
# 2. Respondemos TwiML: <Start><Stream> (con <Parameter to=...>) + <Dial>.
# 3. Twilio abre el WebSocket /ws/twilio y envía audio mu-law 8 kHz en base64 de
#    AMBOS lados de la conversación (both_tracks):
#       pista "inbound"  = quien LLAMA      -> hablante "llamante"
#       pista "outbound" = quien RECIBE     -> hablante "receptor"
# 4. Cada pista acumula sus propios bloques de 3 s de audio PCM16 y se procesa
#    EN SEGUNDO PLANO: transcripción -> VishingAnalyzer -> notificación -> DB.
#    Cada mensaje sale etiquetado con `hablante`, `texto` e `inicio_ms`.
#
# Variables de entorno:
#   VISHGUARD_DESTINO   número real que debe sonar (E.164, ej. +502...)  [obligatoria]
#   PUBLIC_URL          URL pública (ej. https://xxxx.ngrok-free.app)    [recomendada]
#   TWILIO_AUTH_TOKEN   si está definida, se valida la firma de Twilio
#   VISHGUARD_STT       simulado (defecto) | groq
#   GROQ_API_KEY        necesaria si VISHGUARD_STT=groq
#   GROQ_STT_MODEL      defecto whisper-large-v3-turbo
#   VISHGUARD_DEBUG     1 para habilitar /debug/connections
#   VISHGUARD_GUARDAR_WAV  1 para guardar el audio de cada llamada en un .wav (apagado por defecto)
#   VISHGUARD_WAV_DIR      carpeta de las grabaciones (defecto: grabaciones)
#   VISHGUARD_WAV_MAX_SEG  tope de segundos grabados por llamada y por pista (defecto: 600)
#   VISHGUARD_WAV_MODO     estereo (defecto: izq=llamante, der=receptor) | mono (mezcla)
#
# PUNTOS DE EXTENSIÓN (de afuera hacia adentro):
#   * transcribir_audio(pcm8k) -> str   Entrega del equipo de Whisper: se sustituye el cuerpo.
#                                       Entrada: PCM16 mono 8 kHz, bloques de 3 s (48,000 bytes).
#   * _etapa_analisis(texto) -> dict    Único punto donde añadir, más adelante, un interruptor
#                                       para saltarse el análisis de IA.
#   * GrabadorWav                       Verificación: deja en disco lo MISMO que entra a la
#                                       canalización, para escucharlo o entregarlo como muestra.
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
import re
import wave
from datetime import datetime
from pathlib import Path
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

# Pistas de Twilio (desde la perspectiva de Twilio) -> quién habla.
#   inbound  = el audio que Twilio RECIBE de quien llama.
#   outbound = el audio que Twilio GENERA hacia la llamada: la voz de quien recibe
#              (la pierna del <Dial>), pero también puede traer tono de llamada o
#              música en espera mientras nadie contesta.
HABLANTES = {"inbound": "llamante", "outbound": "receptor"}

# Tope de audio grabado por llamada (evita llenar el disco si el WebSocket,
# que no tiene autenticación, recibe un stream interminable).
WAV_MAX_BYTES = BYTES_POR_SEGUNDO * int(os.getenv("VISHGUARD_WAV_MAX_SEG", "600"))

# Referencias fuertes a los análisis en curso: asyncio solo guarda referencias
# débiles a las tareas y podría recolectarlas antes de terminar.
_TAREAS_ACTIVAS: set[asyncio.Task] = set()


def _mask(numero: Optional[str]) -> str:
    return f"***{numero[-4:]}" if numero else "?"


# ==============================================================================
# GRABACIÓN OPCIONAL DEL AUDIO (verificación y muestra para el equipo de Whisper)
# ==============================================================================
class GrabadorWav:
    """Guarda la conversación COMPLETA de UNA llamada como WAV PCM16 de 8 kHz.

    Cada hablante va en su propio canal: izquierdo = llamante, derecho = receptor
    (VISHGUARD_WAV_MODO=mono mezcla ambos en un solo canal). Cada frame se coloca
    según su `timestamp` de Twilio, así que los silencios y los turnos de palabra
    quedan en su sitio aunque una pista empiece más tarde que la otra.

    Está apagado salvo que VISHGUARD_GUARDAR_WAV=1, y NUNCA interrumpe la llamada:
    ante cualquier error se desactiva y deja un warning en el log. El archivo se
    escribe al cerrar (también si Twilio se desconecta de golpe).
    Las grabaciones contienen voz de personas: guárdalas solo con consentimiento
    y no las subas al repositorio (agrega la carpeta al .gitignore).
    """

    def __init__(self, call_sid: Optional[str]) -> None:
        self._pistas = {pista: bytearray() for pista in HABLANTES}
        self._activa = False
        self.ruta: Optional[Path] = None
        if os.getenv("VISHGUARD_GUARDAR_WAV", "").lower() not in ("1", "true", "yes"):
            return
        try:
            carpeta = Path(os.getenv("VISHGUARD_WAV_DIR", "grabaciones"))
            carpeta.mkdir(parents=True, exist_ok=True)
            # El callSid llega por un WebSocket sin autenticar: se deja solo
            # [A-Za-z0-9_-] para que no pueda escapar de la carpeta (../).
            seguro = re.sub(r"[^A-Za-z0-9_-]", "", call_sid or "")[:64] or "sin_sid"
            marca = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.ruta = carpeta / f"{seguro}_{marca}.wav"
            self._volcar()  # comprueba AHORA que se puede escribir (avisa al inicio)
            self._activa = True
            logger.info("Grabando la conversación en %s", self.ruta)
        except Exception:
            self._activa = False
            logger.warning("No se pudo iniciar la grabación WAV; la llamada sigue sin grabar", exc_info=True)

    def escribir(self, pista: str, pcm: bytes, ts_ms: Optional[int] = None) -> None:
        """Añade un frame de la pista `inbound` u `outbound`, alineado por `ts_ms`."""
        if not self._activa or pista not in self._pistas:
            return
        buf = self._pistas[pista]
        inicio = len(buf)
        if ts_ms is not None and ts_ms >= 0:
            inicio = max(inicio, (ts_ms * 16) & ~1)  # 8 muestras/ms x 2 bytes
        # El tope se comprueba ANTES de rellenar huecos: el timestamp viene de un
        # WebSocket sin autenticar y no debe poder reservar memoria arbitraria.
        if inicio + len(pcm) > WAV_MAX_BYTES:
            logger.warning(
                "Tope de grabación alcanzado (%s s): se detiene", WAV_MAX_BYTES // BYTES_POR_SEGUNDO
            )
            self._activa = False
            return
        if inicio > len(buf):
            buf.extend(bytes(inicio - len(buf)))  # silencio hasta el instante del frame
        buf.extend(pcm)

    def cerrar(self) -> None:
        if self.ruta is None or (not self._activa and not self._pistas_con_audio()):
            self._activa = False
            return
        self._activa = False
        try:
            segundos = self._volcar()
            logger.info("Grabación guardada: %s (%.1f s)", self.ruta, segundos)
        except Exception:
            logger.warning("Error guardando la grabación", exc_info=True)
        finally:
            self._pistas = {pista: bytearray() for pista in HABLANTES}

    def _pistas_con_audio(self) -> bool:
        return any(self._pistas.values())

    def _volcar(self) -> float:
        """Escribe el WAV con lo acumulado. Devuelve la duración en segundos."""
        inb, out = self._pistas["inbound"], self._pistas["outbound"]
        largo = max(len(inb), len(out))
        inb = bytes(inb) + bytes(largo - len(inb))  # la pista más corta se rellena con silencio
        out = bytes(out) + bytes(largo - len(out))
        if os.getenv("VISHGUARD_WAV_MODO", "estereo").lower() == "mono":
            canales = 1
            datos = audioop.add(audioop.mul(inb, 2, 0.5), audioop.mul(out, 2, 0.5), 2)
        else:
            canales = 2  # izquierdo = llamante, derecho = receptor
            datos = audioop.add(audioop.tostereo(inb, 2, 1, 0), audioop.tostereo(out, 2, 0, 1), 2)
        with wave.open(str(self.ruta), "wb") as wav:
            wav.setnchannels(canales)
            wav.setsampwidth(2)
            wav.setframerate(8000)
            wav.writeframes(datos)
        return largo / BYTES_POR_SEGUNDO


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

    # Stream del audio de ambos lados de la llamada, sin bloquearla.
    # El número va como <Parameter>, NO en la query string de la URL.
    start = Start()
    # Si el router se incluyó con prefix (ej. /api/v1) el WebSocket cuelga del mismo prefijo.
    prefijo = request.url.path.removesuffix("/twilio/voice")
    # both_tracks: inbound = quien llama; outbound = quien recibe (pierna del <Dial>).
    stream = start.stream(url=f"{ws_base}{prefijo}/ws/twilio", track="both_tracks")
    stream.parameter(name="to", value=destino)  # quien RECIBE (y destino de las alertas)
    llamante = manager.normalizar(form.get("From"))
    if llamante:
        stream.parameter(name="from", value=llamante)  # quien LLAMA
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
async def _etapa_analisis(texto: str) -> dict:
    """ETAPA 2: análisis de fraude (IA).

    Único punto donde, más adelante, se puede añadir un interruptor para
    saltarse el análisis (por ejemplo, devolver aquí un resultado neutro).
    """
    return await asyncio.to_thread(analyzer.analizar_texto, texto)


def _a_int(valor) -> Optional[int]:
    """`media.timestamp` llega como texto ("5"); None si falta o no es un número."""
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


async def _procesar_chunk(
    pcm: bytes,
    destino: Optional[str],
    lock: asyncio.Lock,
    hablante: str = "llamante",
    inicio_ms: Optional[int] = None,
):
    """Procesa un bloque de audio de UN solo hablante.

    El lock mantiene el orden de los resultados de ESE hablante; los dos
    hablantes se procesan en paralelo (el orden entre ellos lo da `inicio_ms`).
    """
    async with lock:
        try:
            # ETAPA 1: transcripción (entrega del equipo de Whisper).
            texto = await asyncio.to_thread(transcribir_audio, pcm)
            if not texto:
                return

            # ETAPA 2: análisis de fraude.
            resultado = await _etapa_analisis(texto)
            # Cada mensaje sale identificado: quién lo dijo, qué dijo y cuándo
            # (milisegundos desde el inicio de la llamada).
            resultado = {**resultado, "hablante": hablante, "texto": texto}
            if inicio_ms is not None:
                resultado["inicio_ms"] = inicio_ms
            logger.info(
                "[VishGuard] %s riesgo=%s score=%s",
                hablante,
                resultado.get("nivel_riesgo"),
                resultado.get("score"),
            )

            # ETAPA 3: notificación a la app.
            if destino:
                await manager.enviar_a(destino, resultado)

            # ETAPA 4: persistencia. Con STT simulado NO se guarda en la DB
            # (evita alertas falsas).
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

    destino = manager.normalizar(to) or None   # quien RECIBE la llamada
    llamante: Optional[str] = None             # quien LLAMA (si Twilio lo envía)
    buffers = {pista: bytearray() for pista in HABLANTES}
    inicios: dict[str, Optional[int]] = {pista: None for pista in HABLANTES}
    # Un lock por hablante: cada uno se procesa en orden, pero sin esperarse entre sí.
    locks = {pista: asyncio.Lock() for pista in HABLANTES}
    tareas: set[asyncio.Task] = set()
    grabador: Optional[GrabadorWav] = None

    def lanzar(pista: str):
        """Envía a la canalización lo acumulado de esa pista y la vacía."""
        pcm = bytes(buffers[pista])
        buffers[pista].clear()
        tarea = asyncio.create_task(
            _procesar_chunk(pcm, destino, locks[pista], HABLANTES[pista], inicios[pista])
        )
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
                llamante = manager.normalizar(params.get("from")) or llamante
                logger.info(
                    "Stream iniciado (callSid=%s, llamante=%s, receptor=%s, pistas=%s)",
                    info.get("callSid"),
                    _mask(llamante),
                    _mask(destino),
                    info.get("tracks"),
                )
                if grabador is not None:
                    grabador.cerrar()
                grabador = GrabadorWav(info.get("callSid"))

            elif event == "media":
                media = data.get("media") or {}
                payload = media.get("payload")
                if not payload:
                    continue
                # Sin campo `track` (stream de una sola pista) se asume "inbound".
                pista = media.get("track") or "inbound"
                if pista not in HABLANTES:
                    continue
                try:
                    raw_mulaw = base64.b64decode(payload, validate=True)
                except (binascii.Error, ValueError):
                    logger.warning("Payload base64 inválido: se descarta el frame")
                    continue
                # mu-law 8 kHz -> PCM lineal 16 bit
                pcm16 = audioop.ulaw2lin(raw_mulaw, 2)
                ts_ms = _a_int(media.get("timestamp"))
                if grabador is None:  # por si no llegó el evento `start`
                    grabador = GrabadorWav(None)
                grabador.escribir(pista, pcm16, ts_ms)

                if not buffers[pista]:
                    inicios[pista] = ts_ms  # instante del primer frame del bloque
                buffers[pista].extend(pcm16)
                if len(buffers[pista]) >= CHUNK_BYTES:
                    lanzar(pista)

            elif event == "stop":
                logger.info("Transmisión finalizada por Twilio")
                for pista in HABLANTES:  # remanente de cada hablante
                    if len(buffers[pista]) >= MIN_REMANENTE_BYTES:
                        lanzar(pista)
                break

            # "connected", "mark", "dtmf": se ignoran

    except WebSocketDisconnect:
        logger.info("Conexión cerrada abruptamente por Twilio")
    except Exception:
        logger.exception("Error en /ws/twilio")
    finally:
        # Cierra el WAV primero: queda completo aunque el análisis tarde.
        if grabador is not None:
            grabador.cerrar()
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