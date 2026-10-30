"""Sección 3: Canal WebSocket de audio (/ws/stream).
Cubre: Handshake, ping-pong, límites de tamaño, inyección por tasa de mensajes, concurrencia por usuario y autenticación JWT.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from modules.Security.rate_limit import ConnectionLimiter

class _ManagerFalso:
    def __init__(self):
        self.conectados, self.desconectados = [], 0
    def normalizar(self, n):
        return n if n.lstrip("+").isdigit() else None
    async def connect(self, ws, numero):
        await ws.accept()
        self.conectados.append(numero)
        return numero
    def disconnect(self, clave, ws):
        self.desconectados += 1

@pytest.fixture
def ws(monkeypatch):
    import api.routes.stream as stream
    monkeypatch.setattr(stream, "manager", _ManagerFalso())
    monkeypatch.setattr(stream, "conn_limiter", ConnectionLimiter(max_per_user=1))
    monkeypatch.setattr(stream, "WS_AUTH_REQUIRED", False)
    app = FastAPI()
    app.include_router(stream.router)
    return stream, TestClient(app)

def test_ws_01_ping_pong_sigue_funcionando(ws):
    _, c = ws
    with c.websocket_connect("/ws/stream?numero=50255551234") as s:
        s.send_text("ping")
        assert s.receive_text() == "pong"

def test_ws_02_mensaje_sobredimensionado_cierra_con_1009(ws):
    _, c = ws
    with c.websocket_connect("/ws/stream?numero=50255551234") as s:
        s.send_text("x" * 5000)
        with pytest.raises(WebSocketDisconnect) as e:
            s.receive_text()
        assert e.value.code == 1009

def test_ws_03_inundacion_de_mensajes_cierra_con_1008(ws, monkeypatch):
    stream, c = ws
    monkeypatch.setattr(stream, "WS_MSG_POR_VENTANA", 3)
    with c.websocket_connect("/ws/stream?numero=50255551234") as s:
        with pytest.raises(WebSocketDisconnect) as e:
            for _ in range(10):
                s.send_text("ping")
                s.receive_text()
        assert e.value.code == 1008

def test_ws_04_segunda_conexion_del_mismo_duenio_se_rechaza(ws):
    stream, c = ws
    with c.websocket_connect("/ws/stream?numero=50255551234"):
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect("/ws/stream?numero=50255559999"):
                pass
    with c.websocket_connect("/ws/stream?numero=50255551234") as s:
        s.send_text("ping")
        assert s.receive_text() == "pong"

def test_ws_05_numero_invalido_se_rechaza(ws):
    _, c = ws
    with pytest.raises(WebSocketDisconnect):
        with c.websocket_connect("/ws/stream?numero=abc"):
            pass

def test_ws_06_con_auth_activa_token_invalido_se_rechaza(ws, monkeypatch):
    stream, c = ws
    monkeypatch.setattr(stream, "WS_AUTH_REQUIRED", True)
    monkeypatch.setattr(stream, "usuario_id_desde_token", lambda t: 7 if t == "ok" else None)
    with pytest.raises(WebSocketDisconnect):
        with c.websocket_connect("/ws/stream?numero=50255551234&token=malo"):
            pass
    with c.websocket_connect("/ws/stream?numero=50255551234&token=ok") as s:
        s.send_text("ping")
        assert s.receive_text() == "pong"
