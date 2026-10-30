"""INTEGRACIÓN - services/analyzer.py (analizador) y api/routes/stream.py (canal WebSocket de alertas).
Cubre: contrato único de respuesta, PII fuera de Gemini, adaptador Gemini (fallback/timeout),
compatibilidad síncrona, límites del canal WS y enmascarado de ?numero= en logs.
Los SDK/servicios externos se simulan; no hay llamadas de red.
"""
import asyncio
import json
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import modules.analyzer as analyzer_mod
from core.log_sanitizer import scrub
from modules.Security.rate_limit import ConnectionLimiter
from modules.resilience import resilience_manager as rm

CONTRATO = {"nivel_riesgo", "score", "mensaje_alerta", "recomendacion"}
PELIGRO = "Soy del banco BBVA, cuenta suspendida, dígame su pin"


def _json(score, nivel="BAJO"):
    return json.dumps({"nivel_riesgo": nivel, "score": score, "mensaje_alerta": "ok", "recomendacion": "ok"})


# ------------------------------ analizador ------------------------------

def test_c01_sin_api_key_usa_solo_motor_local_con_el_mismo_contrato(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(analyzer_mod, "load_dotenv", lambda: None)
    r = analyzer_mod.VishingAnalyzer().analizar_texto(PELIGRO)
    assert set(r) == CONTRATO and r["nivel_riesgo"] == "PELIGROSO"


def test_c02_con_api_key_el_texto_llega_sanitizado_y_prevalece_el_piso(monkeypatch):
    vistos = []
    async def falso(system, user):
        vistos.append(user); return _json(0)               # el LLM "obedece" y minimiza
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(analyzer_mod, "load_dotenv", lambda: None)
    monkeypatch.setattr(analyzer_mod, "gemini_llm_call", lambda *a, **k: falso)
    r = asyncio.run(analyzer_mod.VishingAnalyzer().analizar_texto_async(
        PELIGRO + " mi tarjeta 4539 1488 0343 6467 y correo a@b.com"))
    assert "4539" not in vistos[0] and "a@b.com" not in vistos[0]
    assert r["nivel_riesgo"] == "PELIGROSO"


def test_c03_analizar_texto_sincrono_funciona_con_event_loop_activo(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(analyzer_mod, "load_dotenv", lambda: None)
    a = analyzer_mod.VishingAnalyzer()
    async def desde_endpoint_async():
        return a.analizar_texto(PELIGRO)          # el llamador viejo sigue funcionando
    assert asyncio.run(desde_endpoint_async())["nivel_riesgo"] == "PELIGROSO"


def test_c04_modelos_configurables_por_entorno(monkeypatch):
    capt = {}
    monkeypatch.setenv("GEMINI_API_KEY", "k"); monkeypatch.setenv("GEMINI_MODELS", " m1 , m2 ")
    monkeypatch.setattr(analyzer_mod, "load_dotenv", lambda: None)
    monkeypatch.setattr(analyzer_mod, "gemini_llm_call", lambda k, modelos, **kw: capt.update(m=modelos))
    analyzer_mod.VishingAnalyzer()
    assert capt["m"] == ["m1", "m2"]


# ------------------------------ adaptador Gemini ------------------------------

class _Resp:
    def __init__(self, text): self.text = text

def _cliente_falso(monkeypatch, comportamiento, timeouts=None):
    """comportamiento: dict modelo -> str | Exception | callable"""
    class _Models:
        def generate_content(self, model, contents, config):
            if timeouts is not None:
                timeouts.append(config.http_options.timeout)
            c = comportamiento[model]
            if callable(c): c = c()
            if isinstance(c, Exception): raise c
            return _Resp(c)
    class _Client:
        def __init__(self, api_key=None, **k): self.models = _Models()
    from google import genai
    monkeypatch.setattr(genai, "Client", _Client)


def test_c05_adaptador_hace_fallback_al_siguiente_modelo(monkeypatch):
    _cliente_falso(monkeypatch, {"m1": RuntimeError("429 con clave=SECRETA"), "m2": _json(10)})
    call = rm.gemini_llm_call("k", ["m1", "m2"], timeout=2.0)
    assert json.loads(asyncio.run(call("s", "u")))["score"] == 10


def test_c06_adaptador_falla_si_todos_los_modelos_fallan_y_manager_cae_a_local(monkeypatch):
    _cliente_falso(monkeypatch, {"m1": RuntimeError("x"), "m2": _Resp(None).text or ""})
    call = rm.gemini_llm_call("k", ["m1", "m2"], timeout=2.0)
    r = asyncio.run(rm.ResilienceManager(call).analizar(PELIGRO))
    assert r["nivel_riesgo"] == "PELIGROSO" and set(r) == CONTRATO


def test_c07_adaptador_no_llama_modelos_fuera_de_plazo(monkeypatch):
    llamadas = []
    def lento(): llamadas.append("m1"); time.sleep(0.3); raise RuntimeError("lento")
    _cliente_falso(monkeypatch, {"m1": lento, "m2": _json(1)})
    call = rm.gemini_llm_call("k", ["m1", "m2"], timeout=0.2)
    with pytest.raises(RuntimeError):
        asyncio.run(call("s", "u"))
    assert llamadas == ["m1"]                            # m2 ya no se invoca: se acabó el plazo


def test_c10_el_adaptador_no_envia_cabecera_x_server_timeout(monkeypatch):
    capt = {}
    from google import genai
    real = genai.Client
    def espia(api_key=None, http_options=None):
        capt["opts"] = http_options; return real(api_key=api_key, http_options=http_options)
    monkeypatch.setattr(genai, "Client", espia)
    rm.gemini_llm_call("k", ["m1"], timeout=2.5)
    assert capt["opts"].timeout is None and capt["opts"].client_args == {"timeout": 2.5}

# ------------------------------ canal WebSocket ------------------------------

class _ManagerFalso:
    def __init__(self): self.conectados, self.desconectados = [], 0
    def normalizar(self, n): return n if n.lstrip("+").isdigit() else None
    async def connect(self, ws, numero):
        await ws.accept(); self.conectados.append(numero); return numero
    def disconnect(self, clave, ws): self.desconectados += 1


@pytest.fixture
def ws(monkeypatch):
    import api.routes.stream as stream
    monkeypatch.setattr(stream, "manager", _ManagerFalso())
    monkeypatch.setattr(stream, "conn_limiter", ConnectionLimiter(max_per_user=1))
    monkeypatch.setattr(stream, "WS_AUTH_REQUIRED", False)
    app = FastAPI(); app.include_router(stream.router)
    return stream, TestClient(app)


def test_d01_ping_pong_sigue_funcionando(ws):
    _, c = ws
    with c.websocket_connect("/ws/stream?numero=50255551234") as s:
        s.send_text("ping"); assert s.receive_text() == "pong"


def test_d02_mensaje_sobredimensionado_cierra_con_1009(ws):
    _, c = ws
    with c.websocket_connect("/ws/stream?numero=50255551234") as s:
        s.send_text("x" * 5000)
        with pytest.raises(WebSocketDisconnect) as e: s.receive_text()
        assert e.value.code == 1009


def test_d03_inundacion_de_mensajes_cierra_con_1008(ws, monkeypatch):
    stream, c = ws
    monkeypatch.setattr(stream, "WS_MSG_POR_VENTANA", 3)
    with c.websocket_connect("/ws/stream?numero=50255551234") as s:
        with pytest.raises(WebSocketDisconnect) as e:
            for _ in range(10):
                s.send_text("ping"); s.receive_text()
        assert e.value.code == 1008


def test_d04_segunda_conexion_del_mismo_duenio_se_rechaza_y_se_libera_al_cerrar(ws):
    stream, c = ws
    with c.websocket_connect("/ws/stream?numero=50255551234"):
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect("/ws/stream?numero=50255559999"): pass
    with c.websocket_connect("/ws/stream?numero=50255551234") as s:    # ya liberada
        s.send_text("ping"); assert s.receive_text() == "pong"
    assert stream.manager.desconectados >= 2


def test_d05_la_conexion_se_libera_aunque_el_manager_falle(ws, monkeypatch):
    stream, c = ws
    async def roto(self, w, n): raise RuntimeError("fallo del manager")
    monkeypatch.setattr(_ManagerFalso, "connect", roto)
    with pytest.raises(Exception):
        with c.websocket_connect("/ws/stream?numero=50255551234"): pass
    assert stream.conn_limiter._active == {}


def test_d06_numero_invalido_se_rechaza(ws):
    _, c = ws
    with pytest.raises(WebSocketDisconnect):
        with c.websocket_connect("/ws/stream?numero=abc"): pass


def test_d07_con_auth_activa_token_invalido_se_rechaza_y_valido_entra(ws, monkeypatch):
    stream, c = ws
    monkeypatch.setattr(stream, "WS_AUTH_REQUIRED", True)
    monkeypatch.setattr(stream, "usuario_id_desde_token", lambda t: 7 if t == "ok" else None)
    with pytest.raises(WebSocketDisconnect):
        with c.websocket_connect("/ws/stream?numero=50255551234&token=malo"): pass
    with c.websocket_connect("/ws/stream?numero=50255551234&token=ok") as s:
        s.send_text("ping"); assert s.receive_text() == "pong"


def test_d08_forwarded_solo_se_usa_si_se_confia_en_el_proxy(ws, monkeypatch):
    stream, c = ws
    stream.conn_limiter = ConnectionLimiter(max_per_user=1)
    monkeypatch.setattr(stream, "WS_TRUST_FORWARDED", True)
    h1, h2 = {"x-forwarded-for": "1.1.1.1"}, {"x-forwarded-for": "2.2.2.2"}
    with c.websocket_connect("/ws/stream?numero=50255551234", headers=h1):
        with c.websocket_connect("/ws/stream?numero=50255559999", headers=h2) as s2:   # otro dueño: entra
            s2.send_text("ping"); assert s2.receive_text() == "pong"


def test_d09_log_de_acceso_no_expone_numero_ni_token():
    linea = '127.0.0.1:5555 - "WebSocket /ws/stream?numero=%2B50255551234&token=eyJhbGciOiJIUzI1NiJ9.eyJzIjoxfQ.abc"'
    out = scrub(linea)
    assert "50255551234" not in out and "eyJ" not in out


def test_c11_el_log_enmascara_claves_de_google_con_formato_nuevo():
    clave = "AQ.Ab8RN6K1234567890abcdefghijklmnopqrstuvwxyzABC"
    assert clave not in scrub(f"fallo al llamar con {clave} en la cabecera")
