import asyncio
import logging
import os
from typing import Optional

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from core.connection_manager import manager  # SINGLETON compartido (no crear otro)
from core.ws_auth import usuario_id_desde_token

logger = logging.getLogger("vishguard.stream")

router = APIRouter()

# Con WS_AUTH_REQUIRED=true la app Android debe conectar con ?token=<JWT>.
# Por defecto está apagado para no romper la app actual mientras se actualiza.
WS_AUTH_REQUIRED = os.getenv("WS_AUTH_REQUIRED", "false").lower() in ("1", "true", "yes")


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
        # PENDIENTE: comprobar que `numero` pertenece a ese usuario
        # (depende del campo de teléfono en models.user.User).

    if not manager.normalizar(numero):
        await websocket.close(code=1008)
        return

    clave = await manager.connect(websocket, numero)
    try:
        while True:
            mensaje = await websocket.receive_text()
            if mensaje == "ping":  # keepalive opcional desde la app
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Error en /ws/stream")
    finally:
        # Solo elimina si sigue siendo ESTE socket el registrado
        manager.disconnect(clave, websocket)