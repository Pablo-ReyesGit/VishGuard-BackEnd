"""Sección 4: Streaming Twilio.
Cubre: Webhook /twilio/voice (TwiML both_tracks), ingesta por WebSocket /ws/twilio, AudioFrameGuard, diarización y control de límites.
"""
import base64
import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import api.routes.twilio_stream as tw
from core.connection_manager import manager
from modules.Security.rate_limit import ConnectionLimiter

VOZ = base64.b64encode(bytes([0x20, 0xA0] * 80)).decode()
START_OK = {
    "event": "start",
    "start": {
        "callSid": "CA123",
        "tracks": ["inbound", "outbound"],
        "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1},
        "customParameters": {"to": "50255551234", "from": "50255550000"}
    }
}

def media(payload, i=0, pista="inbound"):
    return json.dumps({"event": "media", "media": {"track": pista, "payload": payload, "timestamp": str(i * 20)}})

def frames(ws, payload, n, pista="inbound"):
    for i in range(n):
        ws.send_text(media(payload, i, pista))

class AnalizadorFalso:
    def __init__(self):
        self.textos = []
    def analizar_texto(self, texto):
        self.textos.append(texto)
        return {"nivel_riesgo": "PELIGROSO", "score": 90, "mensaje_alerta": "m", "recomendacion": "r"}

@pytest.fixture
def env(monkeypatch):
    an = AnalizadorFalso()
    monkeypatch.setattr(tw, "analyzer", an)
    monkeypatch.setattr(tw, "STT_MODE", "simulado")
    monkeypatch.setattr(tw, "_limite_llamadas", ConnectionLimiter(5))
    manager.enviados.clear()
    app = FastAPI()
    app.include_router(tw.router)
    return an, TestClient(app)

def test_tw_01_webhook_devuelve_twiml_con_both_tracks(env, monkeypatch):
    _, c = env
    monkeypatch.setenv("VISHGUARD_DESTINO", "50255551234")
    monkeypatch.setenv("PUBLIC_URL", "https://x.ngrok-free.app")
    r = c.post("/twilio/voice", data={"From": "50255550000"})
    assert r.status_code == 200 and 'track="both_tracks"' in r.text and "wss://x.ngrok-free.app/ws/twilio" in r.text

def test_tw_02_llamada_completa_etiqueta_hablante_y_notifica(env):
    an, c = env
    with c.websocket_connect("/ws/twilio") as ws:
        ws.send_text(json.dumps(START_OK))
        frames(ws, VOZ, 150)
        ws.send_text(json.dumps({"event": "stop"}))
    assert len(manager.enviados) == 1
    destino, alerta = manager.enviados[0]
    assert destino == "50255551234" and alerta["hablante"] == "llamante"

def test_tw_03_las_dos_pistas_se_procesan_con_su_hablante(env):
    _, c = env
    with c.websocket_connect("/ws/twilio") as ws:
        ws.send_text(json.dumps(START_OK))
        frames(ws, VOZ, 150, "inbound")
        frames(ws, VOZ, 150, "outbound")
        ws.send_text(json.dumps({"event": "stop"}))
    assert {a["hablante"] for _, a in manager.enviados} == {"llamante", "receptor"}

def test_tw_04_formato_no_mulaw_cierra_con_1003(env):
    an, c = env
    malo = json.loads(json.dumps(START_OK))
    malo["start"]["mediaFormat"] = {"encoding": "audio/pcm", "sampleRate": 16000}
    with c.websocket_connect("/ws/twilio") as ws:
        ws.send_text(json.dumps(malo))
        with pytest.raises(WebSocketDisconnect) as e:
            ws.receive_text()
        assert e.value.code == 1003
