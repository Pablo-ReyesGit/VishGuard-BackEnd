"""INTEGRACIÓN - api/routes/twilio_stream.py (ingesta de audio de Twilio, Sprint 1-2).
Ejercita el flujo completo por WebSocket: AudioFrameGuard, VAD, buffers volátiles, límites,
contrapresión, sanitización de la alerta y purga de grabaciones. STT, analizador y manager
están simulados; no hay red.
"""
import base64
import json
import os
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import api.routes.twilio_stream as tw
from core.connection_manager import manager
from modules.Security.rate_limit import ConnectionLimiter
from modules.resilience.call_session import LimiteExcedido, SesionLlamada

VOZ = base64.b64encode(bytes([0x20, 0xA0] * 80)).decode()     # 20 ms con energía
SILENCIO = base64.b64encode(b"\xff" * 160).decode()           # 20 ms de silencio
START_OK = {"event": "start", "start": {"callSid": "CA123", "tracks": ["inbound", "outbound"],
            "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1},
            "customParameters": {"to": "50255551234", "from": "50255550000"}}}


def media(payload, i=0, pista="inbound"):
    return json.dumps({"event": "media", "media": {"track": pista, "payload": payload, "timestamp": str(i * 20)}})


def frames(ws, payload, n, pista="inbound"):
    for i in range(n):
        ws.send_text(media(payload, i, pista))


class AnalizadorFalso:
    def __init__(self): self.textos = []
    def analizar_texto(self, texto):
        self.textos.append(texto)
        return {"nivel_riesgo": "PELIGROSO", "score": 90, "mensaje_alerta": "m", "recomendacion": "r"}


@pytest.fixture
def env(monkeypatch, tmp_path):
    for k in ("TWILIO_AUTH_TOKEN", "VISHGUARD_GUARDAR_WAV"):
        monkeypatch.delenv(k, raising=False)
    an = AnalizadorFalso()
    monkeypatch.setattr(tw, "analyzer", an)
    monkeypatch.setattr(tw, "STT_MODE", "simulado")
    monkeypatch.setattr(tw, "_limite_llamadas", ConnectionLimiter(5))
    manager.enviados.clear()
    app = FastAPI(); app.include_router(tw.router)
    return an, TestClient(app)


def cierre(ws):
    with pytest.raises(WebSocketDisconnect) as e:
        ws.receive_text()
    return e.value.code


# ----------------------------- camino deseado -----------------------------

def test_t01_llamada_completa_etiqueta_hablante_y_notifica(env):
    an, c = env
    with c.websocket_connect("/ws/twilio") as ws:
        ws.send_text(json.dumps(START_OK))
        frames(ws, VOZ, 150)                      # 3 s del llamante = un bloque
        ws.send_text(json.dumps({"event": "stop"}))
    assert len(manager.enviados) == 1
    destino, alerta = manager.enviados[0]
    assert destino == "50255551234" and alerta["hablante"] == "llamante" and alerta["inicio_ms"] == 0
    assert alerta["nivel_riesgo"] == "PELIGROSO" and "texto" in alerta


def test_t02_las_dos_pistas_se_procesan_con_su_hablante(env):
    _, c = env
    with c.websocket_connect("/ws/twilio") as ws:
        ws.send_text(json.dumps(START_OK))
        frames(ws, VOZ, 150, "inbound"); frames(ws, VOZ, 150, "outbound")
        ws.send_text(json.dumps({"event": "stop"}))
    assert {a["hablante"] for _, a in manager.enviados} == {"llamante", "receptor"}


def test_t03_webhook_sigue_devolviendo_twiml_con_both_tracks(env, monkeypatch):
    _, c = env
    monkeypatch.setenv("VISHGUARD_DESTINO", "50255551234"); monkeypatch.setenv("PUBLIC_URL", "https://x.ngrok-free.app")
    r = c.post("/twilio/voice", data={"From": "50255550000"})
    assert r.status_code == 200 and 'track="both_tracks"' in r.text and "wss://x.ngrok-free.app/ws/twilio" in r.text


# ----------------------------- AudioFrameGuard / formato -----------------------------

def test_t04_formato_no_mulaw_cierra_con_1003_y_no_analiza(env):
    an, c = env
    malo = json.loads(json.dumps(START_OK)); malo["start"]["mediaFormat"] = {"encoding": "audio/pcm", "sampleRate": 16000}
    with c.websocket_connect("/ws/twilio") as ws:
        ws.send_text(json.dumps(malo))
        assert cierre(ws) == 1003
    assert an.textos == []


def test_t05_start_sin_mediaformat_se_tolera_como_antes(env):
    _, c = env
    sin = json.loads(json.dumps(START_OK)); del sin["start"]["mediaFormat"]
    with c.websocket_connect("/ws/twilio") as ws:
        ws.send_text(json.dumps(sin)); frames(ws, VOZ, 150); ws.send_text(json.dumps({"event": "stop"}))
    assert len(manager.enviados) == 1


def test_t06_tramas_invalidas_se_descartan_y_la_llamada_continua(env):
    _, c = env
    with c.websocket_connect("/ws/twilio") as ws:
        ws.send_text(json.dumps(START_OK))
        ws.send_text(media("!!!no-base64")); ws.send_text(media(base64.b64encode(b"x" * 9000).decode()))
        frames(ws, VOZ, 150); ws.send_text(json.dumps({"event": "stop"}))
    assert len(manager.enviados) == 1


def test_t07_demasiadas_tramas_invalidas_cierra_con_1008(env):
    _, c = env
    with c.websocket_connect("/ws/twilio") as ws:
        ws.send_text(json.dumps(START_OK))
        for _ in range(60): ws.send_text(media("!!!"))
        assert cierre(ws) == 1008


def test_t08_inundacion_de_tramas_cierra_con_1008(env, monkeypatch):
    _, c = env
    monkeypatch.setattr(tw, "MAX_FRAMES_VENTANA", 20)
    with c.websocket_connect("/ws/twilio") as ws:
        ws.send_text(json.dumps(START_OK)); frames(ws, VOZ, 40)
        assert cierre(ws) == 1008


def test_t09_evento_gigante_cierra_con_1009(env, monkeypatch):
    _, c = env
    monkeypatch.setattr(tw, "WS_MAX_MENSAJE", 100)
    with c.websocket_connect("/ws/twilio") as ws:
        ws.send_text("x" * 500)
        assert cierre(ws) == 1009


def test_t10_inactividad_cierra_la_conexion(env, monkeypatch):
    _, c = env
    monkeypatch.setattr(tw, "WS_IDLE_SEG", 0.2)
    with c.websocket_connect("/ws/twilio") as ws:
        assert cierre(ws) == 1000


def test_t11_json_raro_no_tumba_la_llamada(env):
    _, c = env
    with c.websocket_connect("/ws/twilio") as ws:
        for raro in ("[1,2]", '"texto"', "42", "null", json.dumps({"event": "start", "start": [1]}),
                     json.dumps({"event": "start", "start": {"customParameters": "x", "mediaFormat": None}}),
                     json.dumps({"event": "media", "media": "x"}),
                     json.dumps({"event": "media", "media": {"payload": 7}}),
                     json.dumps({"event": "media", "media": {"payload": VOZ, "track": ["a"]}})):
            ws.send_text(raro)
        ws.send_text(json.dumps(START_OK)); frames(ws, VOZ, 150); ws.send_text(json.dumps({"event": "stop"}))
    assert len(manager.enviados) == 1


# ----------------------------- VAD / contrapresión -----------------------------

def test_t12_bloque_sin_voz_no_gasta_stt_pero_con_voz_si(env, monkeypatch):
    _, c = env
    llamadas = []
    monkeypatch.setattr(tw, "STT_MODE", "whisper")
    monkeypatch.setattr(tw, "transcribir_audio", lambda pcm: llamadas.append(len(pcm)) or "hola")
    with c.websocket_connect("/ws/twilio") as ws:
        ws.send_text(json.dumps(START_OK)); frames(ws, SILENCIO, 150)
        ws.send_text(json.dumps({"event": "stop"}))
    assert llamadas == []
    with c.websocket_connect("/ws/twilio") as ws:
        ws.send_text(json.dumps(START_OK)); frames(ws, VOZ, 150); ws.send_text(json.dumps({"event": "stop"}))
    assert llamadas == [48000]


def test_t13_con_stt_simulado_el_silencio_sigue_analizandose_como_antes(env):
    _, c = env
    with c.websocket_connect("/ws/twilio") as ws:
        ws.send_text(json.dumps(START_OK)); frames(ws, SILENCIO, 150); ws.send_text(json.dumps({"event": "stop"}))
    assert len(manager.enviados) == 1


def test_t14_analisis_atrasado_descarta_bloques_en_vez_de_acumular(env, monkeypatch, caplog):
    _, c = env
    def lento(pcm): time.sleep(0.5); return "hola"
    monkeypatch.setattr(tw, "STT_MODE", "whisper"); monkeypatch.setattr(tw, "transcribir_audio", lento)
    monkeypatch.setattr(tw, "MAX_CHUNKS_PENDIENTES", 1)
    with caplog.at_level("WARNING", logger="vishguard.twilio"):
        with c.websocket_connect("/ws/twilio") as ws:
            ws.send_text(json.dumps(START_OK)); frames(ws, VOZ, 450); ws.send_text(json.dumps({"event": "stop"}))
    descartes = [r for r in caplog.records if "atrasado" in r.getMessage()]
    assert len(descartes) == 2               # 3 bloques en 9 s: 1 en análisis, 2 no caben


# ----------------------------- límites de concurrencia -----------------------------

def test_t15_tope_de_llamadas_simultaneas_y_liberacion(env, monkeypatch):
    _, c = env
    monkeypatch.setattr(tw, "_limite_llamadas", ConnectionLimiter(1))
    with c.websocket_connect("/ws/twilio") as ws1:
        ws1.send_text(json.dumps(START_OK))
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect("/ws/twilio"): pass
        ws1.send_text(json.dumps({"event": "stop"}))
    with c.websocket_connect("/ws/twilio") as ws3:       # ya liberada
        ws3.send_text(json.dumps({"event": "stop"}))
    assert tw._limite_llamadas._active == {}


# ----------------------------- privacidad -----------------------------

def test_t16_la_alerta_no_lleva_pii_pero_el_analisis_usa_el_texto_original(env, monkeypatch):
    an, c = env
    pii = "mi tarjeta es 4539 1488 0343 6467, escríbame a juan@mail.com y dígame su pin"
    monkeypatch.setattr(tw, "STT_MODE", "whisper"); monkeypatch.setattr(tw, "transcribir_audio", lambda pcm: pii)
    with c.websocket_connect("/ws/twilio") as ws:
        ws.send_text(json.dumps(START_OK)); frames(ws, VOZ, 150); ws.send_text(json.dumps({"event": "stop"}))
    texto = manager.enviados[0][1]["texto"]
    assert "4539" not in texto and "juan@mail.com" not in texto and "[TARJETA]" in texto
    assert "4539" in an.textos[0]       # el analizador recibe el original (él mismo sanitiza hacia Gemini)


def test_t17_texto_de_la_alerta_se_omite_si_el_sanitizador_falla(monkeypatch):
    from modules.Security.pii_sanitizer import SanitizationError
    monkeypatch.setattr(tw._sanitizador, "sanitize", lambda t: (_ for _ in ()).throw(SanitizationError("x")))
    assert tw._texto_para_alerta("hola") == ""


def test_t18_grabaciones_viejas_se_purgan_por_ttl(tmp_path, monkeypatch):
    monkeypatch.setenv("VISHGUARD_GUARDAR_WAV", "1"); monkeypatch.setenv("VISHGUARD_WAV_DIR", str(tmp_path))
    monkeypatch.setattr(tw, "WAV_TTL_HORAS", 1)
    vieja = tmp_path / "vieja.wav"; vieja.write_bytes(b"x"); os.utime(vieja, (0, 0))
    reciente = tmp_path / "reciente.wav"; reciente.write_bytes(b"x")
    g = tw.GrabadorWav("CA1")
    assert not vieja.exists() and reciente.exists() and g.ruta.exists()


# ----------------------------- SesionLlamada (unitarias) -----------------------------

def _sesion(**k):
    return SesionLlamada(tw.HABLANTES, chunk_bytes=48000, **k)


def test_u01_extraer_vacia_el_buffer_y_reporta_voz():
    s = _sesion(); s.agregar("inbound", b"\x01\x00" * 100, True)
    pcm, voz = s.extraer("inbound")
    assert len(pcm) == 200 and voz and s.vacio("inbound") and s.extraer("inbound") == (b"", False)


def test_u02_reservas_pendientes_respetan_el_tope_y_se_liberan():
    s = _sesion(max_pendientes=2)
    assert s.reservar("inbound") and s.reservar("inbound") and not s.reservar("inbound")
    s.liberar("inbound"); assert s.reservar("inbound")
    s.liberar("outbound"); s.liberar("outbound"); assert s._pend["outbound"] == 0


def test_u03_duracion_maxima_por_pista():
    s = _sesion(max_segundos_por_pista=1)
    with pytest.raises(LimiteExcedido):
        for _ in range(60): s.ingresar("inbound", VOZ)


def test_u04_buffer_lleno_se_reporta_como_limite_y_cerrar_lo_pone_a_cero():
    s = _sesion()
    with pytest.raises(LimiteExcedido):
        for _ in range(10): s.agregar("inbound", b"\x01" * 16000, False)
    s.cerrar()
    assert s.tamano("inbound") == 0


def test_u05_payload_que_no_es_texto_se_descarta():
    s = _sesion()
    assert s.ingresar("inbound", 123) is None and s.ingresar("inbound", None) is None


@pytest.mark.parametrize("fmt,ok", [({"encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1}, True),
                                    ({"encoding": "audio/x-mulaw", "sampleRate": 16000}, False), ("x", False), (None, False)])
def test_u06_formato(fmt, ok):
    assert _sesion().formato_valido(fmt) is ok
