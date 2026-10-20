import asyncio
import io
import logging
import os
import wave
from typing import Optional

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from core.connection_manager import manager  # SINGLETON compartido (no crear otro)
from core.ws_auth import usuario_id_desde_token
from modules.Security.rate_limit import (
    ConnectionLimiter,
    SlidingWindowLimiter,
    TooManyConnections,
    client_key,
)

logger = logging.getLogger("vishguard.stream")

router = APIRouter()


def _env_bool(nombre: str) -> bool:
    return os.getenv(nombre, "false").lower() in ("1", "true", "yes")


# Con WS_AUTH_REQUIRED=true la app Android debe conectar con ?token=<JWT>.
# Por defecto está apagado para no romper la app actual mientras se actualiza.
WS_AUTH_REQUIRED = _env_bool("WS_AUTH_REQUIRED")
# Detrás de ngrok/proxy la IP del peer es la del proxy; activar SOLO si el proxy es de confianza.
WS_TRUST_FORWARDED = _env_bool("WS_TRUST_FORWARDED")
WS_MAX_MSG_CHARS = int(os.getenv("WS_MAX_MSG_CHARS", "256"))       # el cliente solo envía "ping"
WS_MAX_CONN_POR_DUENIO = int(os.getenv("WS_MAX_CONN_POR_USUARIO", "3"))
WS_MSG_POR_VENTANA = int(os.getenv("WS_MSG_POR_VENTANA", "30"))    # mensajes por 10 s y por conexión

conn_limiter = ConnectionLimiter(max_per_user=WS_MAX_CONN_POR_DUENIO)

if not WS_AUTH_REQUIRED:
    logger.warning("WS_AUTH_REQUIRED desactivado: cualquiera puede suscribirse a las alertas de cualquier número")


def pcm_a_wav_bytes(
    pcm_data: bytes, sample_rate=16000, channels=1, sample_width=2
) -> bytes:
    """Empaqueta los bytes PCM recibidos de Android en un contenedor de audio WAV válido."""
    wav_buffer = io.BytesIO()
    with wave.open(wav_buffer, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_data)
    return wav_buffer.getvalue()


@router.websocket("/ws/stream")
async def websocket_endpoint(
    websocket: WebSocket,
    numero: str,
    token: Optional[str] = Query(default=None),
):
    if WS_AUTH_REQUIRED:
        usuario_id = await asyncio.to_thread(usuario_id_desde_token, token)
        if usuario_id is None:
            await websocket.close(code=1008)  # policy violation
            return
        duenio = f"user:{usuario_id}"
    else:
        peer = websocket.client.host if websocket.client else "desconocido"
        duenio = f"ip:{client_key(dict(websocket.headers), peer, WS_TRUST_FORWARDED)}"

    if not manager.normalizar(numero):
        await websocket.close(code=1008)
        return

    try:
        with conn_limiter.hold(duenio):   # libera siempre, aun con excepciones
            await _atender(websocket, numero)
    except TooManyConnections:
        await websocket.close(code=1008)


async def _atender(websocket: WebSocket, numero: str) -> None:
    clave = await manager.connect(websocket, numero)
    ritmo = SlidingWindowLimiter(WS_MSG_POR_VENTANA, 10.0)
    try:
        while True:
            mensaje = await websocket.receive_text()
            if len(mensaje) > WS_MAX_MSG_CHARS:
                await websocket.close(code=1009)  # message too big
                return
            if not ritmo.allow("msg"):
                await websocket.close(code=1008)  # demasiados mensajes
                return
            if mensaje == "ping":  # keepalive opcional desde la app
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Error en /ws/stream")
    finally:
        # Solo elimina si sigue siendo ESTE socket el registrado
        manager.disconnect(clave, websocket)