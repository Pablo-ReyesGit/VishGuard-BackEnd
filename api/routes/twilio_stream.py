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
#   VISHGUARD_STT       motor de transcripción:
#                         simulado (defecto)  NO transcribe: analiza siempre un texto fijo
#                         whisper             faster-whisper local  (modules/stt.py: SpeechToText)
#                         gemini              Gemini multimodal     (modules/stt.py: SpeechToTextService)
#                         groq                Whisper en la API de Groq
#   WHISPER_MODEL       modelo de faster-whisper (defecto: tiny)
#   WHISPER_DEVICE      cpu (defecto) | cuda
#   WHISPER_COMPUTE     int8 (defecto) | float16 | ...
#   GEMINI_API_KEY      necesaria si VISHGUARD_STT=gemini
#   GROQ_API_KEY        necesaria si VISHGUARD_STT=groq
#   GROQ_STT_MODEL      defecto whisper-large-v3-turbo
#   VISHGUARD_DEBUG     1 para habilitar /debug/connections
#   VISHGUARD_LOG_TEXTO 1 imprime en el log lo que dice cada hablante (SOLO PRUEBAS, ver más abajo)
#   VISHGUARD_GUARDAR_WAV  1 para guardar el audio de cada llamada en un .wav (apagado por defecto)
#   VISHGUARD_WAV_DIR      carpeta de las grabaciones (defecto: grabaciones)
#   VISHGUARD_WAV_MAX_SEG  tope de segundos grabados por llamada y por pista (defecto: 600)
#   VISHGUARD_WAV_MODO     estereo (defecto: izq=llamante, der=receptor) | mono (mezcla)
#   --- [S1-2] límites de ingesta (T3/T9) ---
#   VISHGUARD_WAV_TTL_HORAS   las grabaciones más viejas se borran al iniciar otra (defecto: 24)
#   VISHGUARD_MAX_LLAMADAS    llamadas simultáneas aceptadas en /ws/twilio (defecto: 20)
#   VISHGUARD_MAX_FRAME_BYTES tamaño máximo de una trama mu-law (Twilio envía 160) (defecto: 4096)
#   VISHGUARD_MAX_SEG_PISTA   segundos máximos de audio por pista y llamada (defecto: 7200)
#   VISHGUARD_MAX_PENDIENTES  bloques en análisis por pista antes de descartar (defecto: 5)
#   VISHGUARD_MAX_FRAMES_VENTANA  tramas por 5 s y conexión (Twilio envía ~500) (defecto: 1500)
#   VISHGUARD_WS_MAX_MENSAJE  tamaño máximo de un evento JSON, en caracteres (defecto: 65536)
#   VISHGUARD_WS_IDLE_SEG     segundos sin ningún evento antes de cerrar (defecto: 60)
#
# PUNTOS DE EXTENSIÓN (de afuera hacia adentro):
#   * transcribir_audio(pcm8k) -> str   Elige el motor según VISHGUARD_STT (ver arriba).
#                                       Entrada: PCM16 mono 8 kHz, bloques de 3 s (48,000 bytes),
#                                       de UN solo hablante.
#   * _etapa_analisis(texto) -> dict    Único punto donde añadir, más adelante, un interruptor
#                                       para saltarse el análisis de IA.
#   * GrabadorWav                       Verificación: deja en disco lo MISMO que entra a la
#                                       canalización, para escucharlo o entregarlo como muestra.
#
# Dependencias: python-multipart (request.form), twilio, audioop-lts (Python 3.13+),
# groq (solo si VISHGUARD_STT=groq).
# ==============================================================================

import asyncio
import base64  # noqa: F401  (se mantiene por compatibilidad con pruebas existentes)
import binascii  # noqa: F401   x   
import io
import json
import logging
import os
import re
import secrets
import threading
import time
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
from modules.Security.pii_sanitizer import PIISanitizer, SanitizationError          # [S1-2]
from modules.Security.rate_limit import ConnectionLimiter, TooManyConnections        # [S1-2]
from modules.resilience.call_session import LimiteExcedido, SesionLlamada            # [S1-2]

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

# --- [S1-2] Límites de ingesta (T3/T9) -----------------------------------------
WAV_TTL_HORAS = float(os.getenv("VISHGUARD_WAV_TTL_HORAS", "24"))
MAX_LLAMADAS_SIMULTANEAS = int(os.getenv("VISHGUARD_MAX_LLAMADAS", "20"))
MAX_FRAME_BYTES = int(os.getenv("VISHGUARD_MAX_FRAME_BYTES", "4096"))
MAX_SEG_POR_PISTA = int(os.getenv("VISHGUARD_MAX_SEG_PISTA", "7200"))
MAX_CHUNKS_PENDIENTES = int(os.getenv("VISHGUARD_MAX_PENDIENTES", "5"))
MAX_FRAMES_VENTANA = int(os.getenv("VISHGUARD_MAX_FRAMES_VENTANA", "1500"))
WS_MAX_MENSAJE = int(os.getenv("VISHGUARD_WS_MAX_MENSAJE", "65536"))
WS_IDLE_SEG = float(os.getenv("VISHGUARD_WS_IDLE_SEG", "60"))
_limite_llamadas = ConnectionLimiter(max_per_user=MAX_LLAMADAS_SIMULTANEAS)
_sanitizador = PIISanitizer()

# Referencias fuertes a los análisis en curso: asyncio solo guarda referencias
# débiles a las tareas y podría recolectarlas antes de terminar.
_TAREAS_ACTIVAS: set[asyncio.Task] = set()


def _mask(numero: Optional[str]) -> str:
    return f"***{numero[-4:]}" if numero else "?"


def _texto_para_alerta(texto: str) -> str:
    """[S1-2] La alerta (WebSocket a la app + DB) no debe llevar PII: tarjetas, correos,
    teléfonos, PINs... Si el sanitizador falla se omite el texto (fail-closed)."""
    try:
        return _sanitizador.sanitize(texto)
    except SanitizationError:
        return ""


# ==============================================================================
# GRABACIÓN OPCIONAL DEL AUDIO (verificación y muestra para el equipo de Whisper)
# ==============================================================================
def _purgar_antiguas(carpeta: Path) -> None:
    """[S1-2] T3: las grabaciones temporales tienen TTL; se purgan las más viejas."""
    limite = time.time() - WAV_TTL_HORAS * 3600
    for archivo in carpeta.glob("*.wav"):
        try:
            if archivo.stat().st_mtime < limite:
                archivo.unlink()
        except OSError:
            pass


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
            _purgar_antiguas(carpeta)  # [S1-2]
            # El callSid llega por un WebSocket sin autenticar: se deja solo
            # [A-Za-z0-9_-] para que no pueda escapar de la carpeta (../).
            seguro = re.sub(r"[^A-Za-z0-9_-]", "", call_sid or "")[:64] or "sin_sid"
            marca = datetime.now().strftime("%Y%m%d_%H%M%S")
            # Sufijo aleatorio: dos conexiones sin callSid en el mismo segundo no deben
            # pisarse el archivo (pasaba con "sin_sid_<fecha>.wav").
            self.ruta = carpeta / f"{seguro}_{marca}_{secrets.token_hex(2)}.wav"
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


_stt_whisper = None
_stt_gemini = None
_stt_cerrojo = threading.Lock()   # la carga de un modelo ocurre una sola vez


def _get_whisper():
    """faster-whisper local. Se carga al primer uso (puede tardar; ver precargar_stt)."""
    global _stt_whisper
    with _stt_cerrojo:
        if _stt_whisper is None:
            from modules.stt import SpeechToText

            _stt_whisper = SpeechToText()
        return _stt_whisper


def _get_gemini():
    """Gemini multimodal (servicio de la rama Karen)."""
    global _stt_gemini
    with _stt_cerrojo:
        if _stt_gemini is None:
            from modules.stt import SpeechToTextService

            _stt_gemini = SpeechToTextService()
        return _stt_gemini


def precargar_stt() -> None:
    """Carga el motor configurado ANTES de la primera llamada (opcional).

    Con Whisper local el primer bloque tardaría varios segundos en cargar el
    modelo; llámala al arrancar, por ejemplo en el lifespan de main.py:
        await asyncio.to_thread(twilio_stream.precargar_stt)
    """
    if STT_MODE == "whisper":
        _get_whisper()
    elif STT_MODE == "gemini":
        _get_gemini()


# ---------------------------------------------------------------------------
# LOG DE TEXTO (SOLO PARA PRUEBAS)  -  inicio del bloque
# Imprime en el log lo que transcribió cada hablante, para evaluar a mano la
# calidad de Whisper. Apagado por defecto: se activa con VISHGUARD_LOG_TEXTO=1.
# Las conversaciones son datos personales: NO lo dejes activo en producción.
# Para eliminarlo: borra este bloque, la llamada `_log_texto_prueba(...)` en
# `_procesar_chunk` y el `if` marcado en `_avisar_modo_stt`.
# ---------------------------------------------------------------------------
def _log_texto_activo() -> bool:
    return os.getenv("VISHGUARD_LOG_TEXTO", "").lower() in ("1", "true", "yes")


def _log_texto_prueba(hablante: str, texto: str, inicio_ms: Optional[int]) -> None:
    if not _log_texto_activo():
        return
    cuando = f"{inicio_ms / 1000:.1f} s" if inicio_ms is not None else "?"
    logger.info("[TEXTO] %s @ %s: %s", hablante, cuando, texto)
# LOG DE TEXTO (SOLO PARA PRUEBAS)  -  fin del bloque
# ---------------------------------------------------------------------------


_aviso_stt_emitido = False


def _avisar_modo_stt() -> None:
    """Una sola vez por proceso: deja claro qué motor de transcripción está activo."""
    global _aviso_stt_emitido
    if _aviso_stt_emitido:
        return
    _aviso_stt_emitido = True
    if STT_MODE == "simulado":
        logger.warning(
            "STT en modo SIMULADO: NO se transcribe el audio real, siempre se analiza un "
            "texto fijo. Define VISHGUARD_STT=whisper, gemini o groq para transcribir de verdad."
        )
    elif STT_MODE in ("whisper", "gemini", "groq"):
        logger.info("STT activo: %s", STT_MODE)
    else:
        logger.error("VISHGUARD_STT desconocido: %s (usa simulado, whisper, gemini o groq)", STT_MODE)
    if _log_texto_activo():  # LOG DE TEXTO (SOLO PRUEBAS)
        logger.warning(
            "VISHGUARD_LOG_TEXTO activo: lo que dicen las personas se imprime en el log. "
            "Úsalo solo en pruebas y desactívalo después."
        )


def transcribir_audio(pcm8k: bytes) -> str:
    """Transcribe un bloque de audio de UN hablante (PCM16 mono 8 kHz). Corre en un hilo."""
    if STT_MODE == "simulado":
        return "Simulación: Necesitamos confirmación de su clave bancaria por seguridad urgente."

    # Silencio: no gastar un motor de transcripción (ni una llamada a la API)
    if audioop.rms(pcm8k, 2) < UMBRAL_SILENCIO_RMS:
        return ""

    if STT_MODE == "whisper":
        return _get_whisper().transcribir_pcm(pcm8k)

    if STT_MODE == "gemini":
        from modules.stt import pcm8k_a_16k

        return _get_gemini().transcribir_audio_bytes(pcm8k_a_16k(pcm8k))

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
            t0 = time.perf_counter()
            texto = await asyncio.to_thread(transcribir_audio, pcm)
            t_stt = time.perf_counter() - t0
            # ETAPA 1: transcripción (entrega del equipo de Whisper).
            texto = await asyncio.to_thread(transcribir_audio, pcm)
            if not texto:
                return
            _log_texto_prueba(hablante, texto, inicio_ms)  # LOG DE TEXTO (SOLO PRUEBAS)

            # ETAPA 2: análisis de fraude.
            resultado = await _etapa_analisis(texto)
            # Cada mensaje sale identificado: quién lo dijo, qué dijo y cuándo
            # (milisegundos desde el inicio de la llamada).
            # [S1-2] El texto de la alerta sale SIN PII (se analizó el original).
            resultado = {**resultado, "hablante": hablante, "texto": _texto_para_alerta(texto)}
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
                await asyncio.to_thread(
                    guardar_alerta_si_aplica, resultado, numero_destino=destino
                )
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
    try:
        with _limite_llamadas.hold("twilio"):  # [S1-2] T9: tope de llamadas simultáneas
            await _atender_llamada(websocket, to)
    except TooManyConnections:
        logger.warning("Límite de llamadas simultáneas alcanzado: se rechaza el WebSocket")
        await websocket.close(code=1013)  # try again later


async def _atender_llamada(websocket: WebSocket, to: Optional[str]) -> None:
    await websocket.accept()
    _avisar_modo_stt()
    logger.info("Conexión WebSocket establecida con Twilio")

    destino = manager.normalizar(to) or None   # quien RECIBE la llamada
    llamante: Optional[str] = None             # quien LLAMA (si Twilio lo envía)
    # [S1-2] buffers volátiles + AudioFrameGuard + límites, uno por pista
    sesion = SesionLlamada(
        HABLANTES,
        chunk_bytes=CHUNK_BYTES,
        bytes_por_segundo=BYTES_POR_SEGUNDO,
        vad_rms=UMBRAL_SILENCIO_RMS,
        max_frame_bytes=MAX_FRAME_BYTES,
        max_segundos_por_pista=MAX_SEG_POR_PISTA,
        max_pendientes=MAX_CHUNKS_PENDIENTES,
        frames_por_ventana=MAX_FRAMES_VENTANA,
    )
    inicios: dict[str, Optional[int]] = {pista: None for pista in HABLANTES}
    # Un lock por hablante: cada uno se procesa en orden, pero sin esperarse entre sí.
    locks = {pista: asyncio.Lock() for pista in HABLANTES}
    tareas: set[asyncio.Task] = set()
    grabador: Optional[GrabadorWav] = None
    cierre = 1000                              # [S1-2] código con el que se cierra el socket

    def lanzar(pista: str):
        """Envía a la canalización lo acumulado de esa pista y la vacía."""
        pcm, hubo_voz = sesion.extraer(pista)
        if not pcm:
            return
        # [S1-2] VAD: un bloque sin una sola trama con voz no gasta STT ni IA
        # (con STT simulado se mantiene el comportamiento original).
        if STT_MODE != "simulado" and not hubo_voz:
            return
        # [S1-2] contrapresión: si el análisis va muy atrasado, se descarta en vez de acumular
        if not sesion.reservar(pista):
            logger.warning("Análisis atrasado en la pista %s: se descarta un bloque", pista)
            return
        tarea = asyncio.create_task(
            _procesar_chunk(pcm, destino, locks[pista], HABLANTES[pista], inicios[pista])
        )
        tareas.add(tarea)
        _TAREAS_ACTIVAS.add(tarea)
        tarea.add_done_callback(tareas.discard)
        tarea.add_done_callback(_TAREAS_ACTIVAS.discard)
        tarea.add_done_callback(lambda _t, p=pista: sesion.liberar(p))

    try:
        while True:
            try:
                # [S1-2] timeout por inactividad: Twilio envía tramas cada 20 ms
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=WS_IDLE_SEG)
            except asyncio.TimeoutError:
                logger.warning("Sin eventos de Twilio durante %s s: se cierra la conexión", WS_IDLE_SEG)
                break
            if len(raw) > WS_MAX_MENSAJE:  # [S1-2]
                logger.warning("Evento demasiado grande (%s caracteres): se cierra la conexión", len(raw))
                cierre = 1009
                break
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict):  # [S1-2] JSON válido pero no es un evento
                continue

            event = data.get("event")

            if event == "start":
                info = data.get("start")
                info = info if isinstance(info, dict) else {}
                params = info.get("customParameters")
                params = params if isinstance(params, dict) else {}
                # [S1-2] T9: solo se acepta mu-law 8 kHz mono (si Twilio informa el formato)
                formato = info.get("mediaFormat")
                if formato is not None and not sesion.formato_valido(formato):
                    logger.warning("Formato de audio no soportado: se cierra el stream")
                    cierre = 1003
                    break
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
                media = data.get("media")
                media = media if isinstance(media, dict) else {}
                payload = media.get("payload")
                if not payload:
                    continue
                # Sin campo `track` (stream de una sola pista) se asume "inbound".
                pista = media.get("track") or "inbound"
                if not isinstance(pista, str) or pista not in HABLANTES:
                    continue
                # [S1-2] AudioFrameGuard: base64, tamaño, ritmo y duración; VAD por trama
                try:
                    trama = sesion.ingresar(pista, payload)
                except LimiteExcedido as exc:
                    logger.warning("Ingesta rechazada: %s", exc.motivo)
                    cierre = 1008
                    break
                if trama is None:
                    logger.warning("Trama inválida: se descarta el frame")
                    continue
                raw_mulaw, hay_voz = trama
                # mu-law 8 kHz -> PCM lineal 16 bit
                pcm16 = audioop.ulaw2lin(raw_mulaw, 2)
                ts_ms = _a_int(media.get("timestamp"))
                if grabador is None:  # por si no llegó el evento `start`
                    grabador = GrabadorWav(None)
                grabador.escribir(pista, pcm16, ts_ms)

                if sesion.vacio(pista):
                    inicios[pista] = ts_ms  # instante del primer frame del bloque
                try:
                    sesion.agregar(pista, pcm16, hay_voz)
                except LimiteExcedido as exc:
                    logger.warning("Ingesta rechazada: %s", exc.motivo)
                    cierre = 1008
                    break
                if sesion.bloque_listo(pista):
                    lanzar(pista)

            elif event == "stop":
                logger.info("Transmisión finalizada por Twilio")
                for pista in HABLANTES:  # remanente de cada hablante
                    if sesion.tamano(pista) >= MIN_REMANENTE_BYTES:
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
        sesion.cerrar()  # [S1-2] T3: los buffers de audio se ponen a cero y se liberan
        # Deja terminar los análisis pendientes (incluye el remanente).
        # shield: si el servidor cancela este handler por una desconexión
        # abrupta, los análisis NO se cancelan y terminan en segundo plano.
        if tareas:
            await asyncio.shield(asyncio.gather(*tareas, return_exceptions=True))
        try:
            await websocket.close(code=cierre)
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
