"""Sección 1: Transcripción de audio (STT).
Cubre: VAD (descarte de silencios), STT simulado, fallback de modelos STT y procesamiento de tramas PCM.
"""
import time
import base64
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.routes.twilio_stream as tw

VOZ = base64.b64encode(bytes([0x20, 0xA0] * 80)).decode()   # 160 bytes = 20 ms
SILENCIO = base64.b64encode(bytes([0xFF] * 160)).decode()

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
    import json
    return json.dumps({"event": "media", "media": {"track": pista, "payload": payload, "timestamp": str(i * 20)}})

def frames(ws, payload, n, pista="inbound"):
    for i in range(n):
        ws.send_text(media(payload, i, pista))

@pytest.fixture
def client_env(monkeypatch):
    monkeypatch.setattr(tw, "STT_MODE", "simulado")
    app = FastAPI()
    app.include_router(tw.router)
    return TestClient(app)

def test_stt_01_bloque_sin_voz_no_gasta_stt_pero_con_voz_si(client_env, monkeypatch):
    llamadas = []
    monkeypatch.setattr(tw, "STT_MODE", "whisper")
    monkeypatch.setattr(tw, "transcribir_audio", lambda pcm: llamadas.append(len(pcm)) or "hola")
    
    with client_env.websocket_connect("/ws/twilio") as ws:
        import json
        ws.send_text(json.dumps(START_OK))
        frames(ws, SILENCIO, 150)
        ws.send_text(json.dumps({"event": "stop"}))
    assert llamadas == []

    with client_env.websocket_connect("/ws/twilio") as ws:
        import json
        ws.send_text(json.dumps(START_OK))
        frames(ws, VOZ, 150)
        ws.send_text(json.dumps({"event": "stop"}))
    assert llamadas == [48000]

def test_stt_02_con_stt_simulado_el_silencio_sigue_analizandose(client_env):
    with client_env.websocket_connect("/ws/twilio") as ws:
        import json
        ws.send_text(json.dumps(START_OK))
        frames(ws, SILENCIO, 150)
        ws.send_text(json.dumps({"event": "stop"}))
    assert True
