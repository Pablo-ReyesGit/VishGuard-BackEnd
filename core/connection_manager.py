import logging
from typing import Dict, Optional

from fastapi import WebSocket

logger = logging.getLogger("vishguard.ws")


class ConnectionManager:
    """Registro de WebSockets de la app, indexados por número de teléfono.

    IMPORTANTE: usar SIEMPRE la instancia `manager` de este módulo
    (`from core.connection_manager import manager`). No crear otra con
    `ConnectionManager()` en otros archivos.
    """

    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    @staticmethod
    def normalizar(numero: Optional[str]) -> str:
        """Devuelve el número como '+<dígitos>'.

        Resuelve el caso en que '+502...' llega como ' 502...' porque el '+'
        de una query string se decodifica como espacio.
        """
        digitos = "".join(c for c in (numero or "") if c.isdigit())
        return f"+{digitos}" if digitos else ""

    async def connect(self, websocket: WebSocket, numero: str) -> str:
        clave = self.normalizar(numero)
        await websocket.accept()
        anterior = self.active_connections.get(clave)
        self.active_connections[clave] = websocket
        # Una sola conexión por número: la nueva reemplaza a la anterior.
        if anterior is not None and anterior is not websocket:
            try:
                await anterior.close(code=1000)
            except Exception:
                pass
        return clave

    def disconnect(self, numero: str, websocket: Optional[WebSocket] = None):
        """Quita la conexión. Si se pasa `websocket`, solo la quita si sigue
        siendo la registrada (evita borrar una reconexión más nueva)."""
        clave = self.normalizar(numero)
        actual = self.active_connections.get(clave)
        if actual is None:
            return
        if websocket is None or actual is websocket:
            self.active_connections.pop(clave, None)

    async def enviar_a(self, numero: str, mensaje: dict) -> bool:
        """Envía JSON a la app. Nunca lanza excepción: devuelve True/False."""
        clave = self.normalizar(numero)
        conexion = self.active_connections.get(clave)
        if conexion is None:
            logger.warning("No hay conexión activa para ***%s", clave[-4:])
            return False
        try:
            await conexion.send_json(mensaje)
            return True
        except Exception:
            logger.warning("Socket muerto para ***%s, se elimina", clave[-4:])
            self.disconnect(clave, conexion)
            return False


# Instancia única, compartida por TODA la aplicación
manager = ConnectionManager()