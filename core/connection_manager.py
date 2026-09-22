from typing import Dict
from fastapi import WebSocket

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, numero: str):
        await websocket.accept()
        self.active_connections[numero] = websocket

    def disconnect(self, numero: str):
        self.active_connections.pop(numero, None)

    async def enviar_a(self, numero: str, mensaje: dict):
        conexion = self.active_connections.get(numero)
        if conexion:
            await conexion.send_json(mensaje)
        else:
            print(f"⚠️ [ConnectionManager] No hay conexión activa para {numero}")

# Instancia única, compartida por TODA la aplicación
manager = ConnectionManager()