"""
pytest - VishGuard / Twilio - pruebas adaptadas al código real.

Prueba directamente estos módulos:
    twilio_stream.py        POST /twilio/voice  y  WS /ws/twilio
    stream.py               WS /ws/stream  (app Android)
    core/connection_manager.py, core/alert_service.py, core/ws_auth.py

Las dependencias externas (Whisper/Groq, VishingAnalyzer, base de datos) se
reemplazan con fakes; Twilio se simula enviando los mismos eventos JSON que
envía Media Streams (connected, start, media, stop).

Cómo ejecutar (desde la raíz del proyecto, con pytest.ini en la raíz):
    pip install pytest fastapi httpx python-multipart twilio pyjwt sqlmodel
    pytest -v

Variables opcionales:
    VISHGUARD_ROUTERS_PKG   paquete donde viven stream.py y twilio_stream.py
                            (ej. "app.routers"). Vacío = raíz del proyecto.
    VISHGUARD_APP_MODULE / VISHGUARD_APP_ATTRIBUTE
                            app real para el smoke test (por defecto main.app).

Correspondencia con la plantilla original (TC-AUTO / E01-E20):
    - Las pruebas que solo verificaban fakes propios (InMemoryStreamManager,
      `assert True`) se reemplazaron por pruebas contra el código real.
    - Lo que el backend actual NO implementa queda como `skip` con el motivo:
      TC-014 (corte por REST), TC-015 (status callback), E05/E15 (timeouts),
      E13 (deduplicación de alertas).
"""

from __future__ import annotations

import asyncio
import importlib
import os
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402


# ============================================================================
# CONSTANTES
# ============================================================================

DESTINO = "+50257008032"
DESTINO_URLENC = "%2B50257008032"
LLAMANTE = "+50255551234"   # quien LLAMA (el `From` del webhook)
CALL_SID = "CA1234567890"
STREAM_SID = "MZ123"

VOICE_ENDPOINT = "/twilio/voice"
TWILIO_WS = "/ws/twilio"
APP_WS = "/ws/stream"

# Un frame de Twilio = 20 ms = 160 bytes mu-law = 320 bytes PCM16 (8 kHz).
MULAW_BYTES_POR_FRAME = 160
PCM_BYTES_POR_FRAME = 320
FRAMES_3S = 150            # 150 x 320 = 48,000 bytes = 3 s (CHUNK_BYTES)
CHUNK_BYTES = 48_000
MIN_REMANENTE_BYTES = 8_000  # 0.5 s


# ============================================================================
# IMPORTS DE LOS MÓDULOS REALES
# ============================================================================

_PKG = os.getenv("VISHGUARD_ROUTERS_PKG", "").strip(".")
_ROOT = Path(__file__).resolve().parent.parent  # raíz del proyecto (tests/..)
_IGNORAR = {"tests", "test", "venv", "env", "node_modules", "build", "dist",
            "site-packages", "__pycache__"}


def _buscar_archivos(name: str):
    """Rutas punteadas de todos los `<name>.py` del proyecto (sin .venv ni tests)."""
    for dirpath, dirnames, filenames in os.walk(_ROOT):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in _IGNORAR]
        if f"{name}.py" in filenames:
            rel = Path(dirpath, f"{name}.py").relative_to(_ROOT).with_suffix("")
            yield ".".join(rel.parts)


def _router_module(name: str):
    """Importa `stream` / `twilio_stream` estén donde estén.

    Orden: VISHGUARD_ROUTERS_PKG -> raíz -> búsqueda por carpetas (api/routes, ...).
    Un ModuleNotFoundError por una dependencia que falta DENTRO del módulo
    (p. ej. audioop) no se oculta: se propaga con su mensaje real.
    """
    candidatos = ([f"{_PKG}.{name}"] if _PKG else []) + [name]
    probados: List[str] = []

    def intentar(dotted: str):
        probados.append(dotted)
        try:
            return importlib.import_module(dotted)
        except ModuleNotFoundError as exc:
            ausente = bool(exc.name) and (dotted == exc.name or dotted.startswith(exc.name + "."))
            if not ausente:
                raise
            return None

    for dotted in candidatos:
        modulo = intentar(dotted)
        if modulo is not None:
            return modulo
    for dotted in _buscar_archivos(name):
        if dotted in probados:
            continue
        modulo = intentar(dotted)
        if modulo is not None:
            return modulo

    pytest.fail(
        f"No se encontró '{name}.py' en {_ROOT}. Probado: {probados}. "
        f"Defina VISHGUARD_ROUTERS_PKG con el paquete donde vive (ej. api.routes).",
        pytrace=False,
    )


@pytest.fixture(scope="session")
def twilio_stream_mod():
    return _router_module("twilio_stream")


@pytest.fixture(scope="session")
def stream_mod():
    return _router_module("stream")


@pytest.fixture(scope="session")
def cm_mod():
    return importlib.import_module("core.connection_manager")


@pytest.fixture(scope="session")
def alert_service_mod():
    return importlib.import_module("core.alert_service")


@pytest.fixture(scope="session")
def ws_auth_mod():
    return importlib.import_module("core.ws_auth")


# ============================================================================
# FAKES
# ============================================================================

class FakeSTT:
    """Reemplaza transcribir_audio(pcm8k) -> str. Se ejecuta en un hilo."""

    def __init__(self) -> None:
        self.calls: List[int] = []           # tamaño en bytes de cada chunk
        self.behaviors: Dict[int, Any] = {}  # índice de llamada -> str | Exception
        self.default_text = "necesitamos su clave bancaria urgente"
        self.delay = 0.0
        # Si se define, el texto depende del audio recibido (permite distinguir hablantes).
        self.clasificar: Optional[Callable[[bytes], str]] = None
        self.max_concurrentes = 0           # llamadas simultáneas observadas
        self._activos = 0
        self._cerrojo = threading.Lock()

    def __call__(self, pcm: bytes) -> str:
        idx = len(self.calls)
        self.calls.append(len(pcm))
        with self._cerrojo:
            self._activos += 1
            self.max_concurrentes = max(self.max_concurrentes, self._activos)
        try:
            if self.delay:
                time.sleep(self.delay)
            if self.clasificar is not None:
                return self.clasificar(pcm)
            behavior = self.behaviors.get(idx, self.default_text)
            if isinstance(behavior, Exception):
                raise behavior
            return behavior
        finally:
            with self._cerrojo:
                self._activos -= 1


class FakeAnalyzer:
    """Reemplaza VishingAnalyzer."""

    def __init__(self) -> None:
        self.calls: List[str] = []
        self.behaviors: Dict[int, Any] = {}  # índice -> dict | Exception
        self.default = {
            "nivel_riesgo": "PELIGROSO",
            "score": 0.92,
            "patrones_detectados": ["urgencia", "clave"],
            "frase_critica": "clave bancaria",
            "recomendacion": "Cuelgue",
        }

    def analizar_texto(self, texto: str) -> dict:
        idx = len(self.calls)
        self.calls.append(texto)
        behavior = self.behaviors.get(idx, self.default)
        if isinstance(behavior, Exception):
            raise behavior
        return dict(behavior)


class FakePersist:
    """Reemplaza guardar_alerta_si_aplica dentro de twilio_stream."""

    def __init__(self) -> None:
        self.rows: List[dict] = []
        self.fail = False

    def __call__(self, evaluacion: dict) -> bool:
        if self.fail:
            raise RuntimeError("AlertHistory DB unavailable")
        self.rows.append(evaluacion)
        return True


class FakeManager:
    """Registra lo que twilio_stream envía a la app, sin sockets reales."""

    def __init__(self, real_cls) -> None:
        self.sent: List[tuple] = []
        self.normalizar = real_cls.normalizar
        self.active_connections: Dict[str, Any] = {}

    async def enviar_a(self, numero: str, mensaje: dict) -> bool:
        self.sent.append((numero, mensaje))
        return True


class FakeWS:
    """WebSocket falso para probar ConnectionManager de forma aislada."""

    def __init__(self, fail_send: bool = False) -> None:
        self.accepted = False
        self.closed = False
        self.sent: List[dict] = []
        self.fail_send = fail_send

    async def accept(self) -> None:
        self.accepted = True

    async def close(self, code: int = 1000) -> None:
        self.closed = True

    async def send_json(self, mensaje: dict) -> None:
        if self.fail_send:
            raise RuntimeError("socket cerrado")
        self.sent.append(mensaje)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture(autouse=True)
def entorno(monkeypatch):
    """Entorno determinista para cada prueba."""
    monkeypatch.setenv("VISHGUARD_DESTINO", DESTINO)
    monkeypatch.setenv("PUBLIC_URL", "http://testserver")
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("VISHGUARD_DEBUG", raising=False)


@pytest.fixture(autouse=True)
def limpiar_manager_real(cm_mod):
    cm_mod.manager.active_connections.clear()
    yield
    cm_mod.manager.active_connections.clear()


@pytest.fixture
def fakes(monkeypatch, twilio_stream_mod):
    """STT, analizador y persistencia falsos (persistencia ACTIVA: modo groq)."""
    stt, analyzer, persist = FakeSTT(), FakeAnalyzer(), FakePersist()
    monkeypatch.setattr(twilio_stream_mod, "transcribir_audio", stt)
    monkeypatch.setattr(twilio_stream_mod, "analyzer", analyzer)
    monkeypatch.setattr(twilio_stream_mod, "guardar_alerta_si_aplica", persist)
    monkeypatch.setattr(twilio_stream_mod, "STT_MODE", "groq")
    return SimpleNamespace(stt=stt, analyzer=analyzer, persist=persist)


@pytest.fixture
def fake_manager(monkeypatch, twilio_stream_mod, cm_mod):
    fm = FakeManager(cm_mod.ConnectionManager)
    monkeypatch.setattr(twilio_stream_mod, "manager", fm)
    return fm


@pytest.fixture
def app(stream_mod, twilio_stream_mod):
    application = FastAPI()
    application.include_router(stream_mod.router)
    application.include_router(twilio_stream_mod.router)
    return application


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


# ============================================================================
# UTILIDADES
# ============================================================================

def twilio_form(call_sid: str = CALL_SID) -> Dict[str, str]:
    return {
        "CallSid": call_sid,
        "From": "+50255551234",
        "To": "+18005559999",
        "CallStatus": "ringing",
    }


def parse_twiml(response) -> ET.Element:
    root = ET.fromstring(response.content)
    assert root.tag == "Response"
    return root


def ev_start(destino: Optional[str] = DESTINO, llamante: Optional[str] = None) -> dict:
    custom = {"to": destino} if destino else {}
    if llamante:
        custom["from"] = llamante
    return {
        "event": "start",
        "streamSid": STREAM_SID,
        "start": {
            "streamSid": STREAM_SID,
            "callSid": CALL_SID,
            "tracks": ["inbound", "outbound"],
            "customParameters": custom,
            "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000},
        },
    }


def ev_media(pista: Optional[str] = None, ts_ms: Optional[int] = None, byte: int = 0xFF) -> dict:
    """Frame de 20 ms. `pista` = "inbound"/"outbound" (None = sin campo, como una sola pista)."""
    import base64

    payload = base64.b64encode(bytes([byte] * MULAW_BYTES_POR_FRAME)).decode()
    media: Dict[str, Any] = {"payload": payload}
    if pista:
        media["track"] = pista
    if ts_ms is not None:
        media["timestamp"] = str(ts_ms)
    return {"event": "media", "streamSid": STREAM_SID, "media": media}


def send_audio(ws, frames: int, pista: Optional[str] = None,
               inicio_ms: Optional[int] = None, byte: int = 0xFF) -> None:
    for i in range(frames):
        ts = None if inicio_ms is None else inicio_ms + 20 * i
        ws.send_json(ev_media(pista, ts, byte))


def finish_call(ws) -> None:
    """Envía `stop` y espera a que el servidor termine (cierra el socket)."""
    ws.send_json({"event": "stop", "streamSid": STREAM_SID})
    with pytest.raises(WebSocketDisconnect):
        ws.receive_json()


def wait_until(predicate: Callable[[], bool], timeout: float = 3.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def recv_json_timeout(ws, timeout: float = 5.0) -> dict:
    """receive_json con tiempo máximo, para que un fallo no cuelgue pytest."""
    box: Dict[str, Any] = {}

    def run():
        try:
            box["value"] = ws.receive_json()
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        pytest.fail("La app no recibió la alerta (¿manager duplicado o sin envío?)")
    if "error" in box:
        raise box["error"]
    return box["value"]


# ============================================================================
# TC-AUTO-011  WEBHOOK DE VOZ  (POST /twilio/voice)
# ============================================================================

@pytest.mark.integration
@pytest.mark.twilio
def test_tc_auto_011_voice_webhook_returns_valid_twiml(client):
    """TwiML con <Start><Stream> (+<Parameter to>) y luego <Dial>; sin <Connect>."""
    response = client.post(VOICE_ENDPOINT, data=twilio_form())

    assert response.status_code == 200
    assert "xml" in response.headers["content-type"].lower()

    root = parse_twiml(response)
    assert [child.tag for child in root] == ["Start", "Dial"]
    assert root.find("Connect") is None  # el stream no debe bloquear la llamada

    stream = root.find("Start/Stream")
    assert stream is not None
    assert stream.attrib["url"] == "ws://testserver/ws/twilio"
    assert stream.attrib.get("track") == "both_tracks"   # ambos lados de la conversación

    parametros = {p.attrib["name"]: p.attrib["value"] for p in stream.findall("Parameter")}
    assert parametros == {"to": DESTINO, "from": LLAMANTE}   # receptor y llamante

    dial = root.find("Dial")
    assert dial.attrib.get("answerOnBridge", "").lower() == "true"
    assert dial.find("Number").text == DESTINO


@pytest.mark.integration
@pytest.mark.twilio
def test_tc_auto_011_ws_url_uses_wss_behind_https_proxy(client, monkeypatch):
    monkeypatch.delenv("PUBLIC_URL", raising=False)
    response = client.post(
        VOICE_ENDPOINT,
        data=twilio_form(),
        headers={"host": "abc.ngrok-free.app", "x-forwarded-proto": "https"},
    )
    assert response.status_code == 200
    stream = parse_twiml(response).find("Start/Stream")
    assert stream.attrib["url"] == "wss://abc.ngrok-free.app/ws/twilio"


# ============================================================================
# TC-AUTO-012  FIRMA X-Twilio-Signature
# ============================================================================

@pytest.fixture
def firma_activa(monkeypatch):
    """Activa la validación de firma y devuelve (token, url pública)."""
    pytest.importorskip("twilio")
    token = "test_auth_token"
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", token)
    return token, "http://testserver" + VOICE_ENDPOINT


@pytest.mark.integration
@pytest.mark.twilio
@pytest.mark.security
def test_tc_auto_012_missing_signature_is_rejected(client, firma_activa):
    response = client.post(VOICE_ENDPOINT, data=twilio_form())
    assert response.status_code == 403
    assert "<Stream" not in response.text


@pytest.mark.integration
@pytest.mark.twilio
@pytest.mark.security
def test_tc_auto_012_invalid_signature_is_rejected(client, firma_activa):
    response = client.post(
        VOICE_ENDPOINT,
        data=twilio_form(),
        headers={"X-Twilio-Signature": "firma_invalida_o_falsificada"},
    )
    assert response.status_code == 403
    assert "<Stream" not in response.text


@pytest.mark.integration
@pytest.mark.twilio
@pytest.mark.security
def test_tc_auto_012_tampered_body_is_rejected(client, firma_activa):
    """Firma válida para unos parámetros, pero el cuerpo fue modificado."""
    from twilio.request_validator import RequestValidator

    token, url = firma_activa
    firma = RequestValidator(token).compute_signature(url, twilio_form("CA_ORIGINAL"))
    response = client.post(
        VOICE_ENDPOINT,
        data=twilio_form("CA_MANIPULADO"),
        headers={"X-Twilio-Signature": firma},
    )
    assert response.status_code == 403


@pytest.mark.integration
@pytest.mark.twilio
@pytest.mark.security
def test_tc_auto_012_valid_signature_is_accepted(client, firma_activa):
    from twilio.request_validator import RequestValidator

    token, url = firma_activa
    form = twilio_form()
    firma = RequestValidator(token).compute_signature(url, form)

    response = client.post(
        VOICE_ENDPOINT, data=form, headers={"X-Twilio-Signature": firma}
    )
    assert response.status_code == 200
    assert parse_twiml(response).find("Start/Stream") is not None


@pytest.mark.integration
@pytest.mark.twilio
@pytest.mark.security
def test_tc_auto_012_without_token_configured_webhook_is_open(client):
    """Documenta el comportamiento actual: sin TWILIO_AUTH_TOKEN no se valida
    la firma (solo se registra un warning). En producción debe estar definido."""
    response = client.post(VOICE_ENDPOINT, data=twilio_form())
    assert response.status_code == 200


# ============================================================================
# TC-AUTO-013  TWILIO MEDIA STREAMS (WS /ws/twilio)
# ============================================================================

@pytest.mark.integration
@pytest.mark.twilio
@pytest.mark.websocket
def test_tc_auto_013_media_stream_full_pipeline(client, fakes, fake_manager):
    """connected -> start -> 150 frames -> chunk de 3 s -> STT -> análisis ->
    notificación a la app (destino tomado de customParameters) -> persistencia."""
    with client.websocket_connect(TWILIO_WS) as ws:
        ws.send_json({"event": "connected", "protocol": "Call", "version": "1.0.0"})
        ws.send_json(ev_start())
        send_audio(ws, FRAMES_3S)
        finish_call(ws)

    assert fakes.stt.calls == [CHUNK_BYTES]
    assert len(fakes.analyzer.calls) == 1

    assert len(fake_manager.sent) == 1
    numero, mensaje = fake_manager.sent[0]
    assert numero == DESTINO
    assert mensaje["nivel_riesgo"] == "PELIGROSO"

    assert len(fakes.persist.rows) == 1


@pytest.mark.integration
@pytest.mark.twilio
@pytest.mark.websocket
def test_tc_auto_013_destination_fallback_from_query_param(client, fakes, fake_manager):
    """Respaldo: si no hay customParameters, se usa ?to= (normalizado)."""
    with client.websocket_connect(f"{TWILIO_WS}?to={DESTINO_URLENC}") as ws:
        ws.send_json(ev_start(destino=None))
        send_audio(ws, FRAMES_3S)
        finish_call(ws)

    assert [n for n, _ in fake_manager.sent] == [DESTINO]


@pytest.mark.integration
@pytest.mark.twilio
@pytest.mark.websocket
def test_e2e_alert_reaches_android_app_with_real_manager(client, fakes):
    """Regresión del bug crítico: la app conectada en /ws/stream recibe lo que
    twilio_stream envía (misma instancia de ConnectionManager)."""
    with client.websocket_connect(f"{APP_WS}?numero={DESTINO_URLENC}") as app_ws:
        with client.websocket_connect(TWILIO_WS) as tw:
            tw.send_json(ev_start())
            send_audio(tw, FRAMES_3S)
            finish_call(tw)

        alerta = recv_json_timeout(app_ws)

    assert alerta["nivel_riesgo"] == "PELIGROSO"
    assert alerta["score"] == pytest.approx(0.92)


@pytest.mark.unit
def test_regression_single_manager_instance(stream_mod, twilio_stream_mod, cm_mod):
    assert stream_mod.manager is cm_mod.manager
    assert twilio_stream_mod.manager is cm_mod.manager


# ============================================================================
# TC-AUTO-014 / TC-AUTO-015  (NO IMPLEMENTADOS EN EL BACKEND ACTUAL)
# ============================================================================

@pytest.mark.skip(reason="No implementado: no hay corte de llamada vía Twilio REST "
                         "(update call status=completed) cuando el riesgo es crítico.")
def test_tc_auto_014_critical_risk_terminates_call():
    ...


@pytest.mark.skip(reason="No implementado: no existe endpoint de StatusCallback "
                         "(CallStatus=completed) en el backend.")
def test_tc_auto_015_status_callback_completed():
    ...


# ============================================================================
# E01  /ws/stream RECHAZA NÚMEROS INVÁLIDOS
# ============================================================================

@pytest.mark.integration
@pytest.mark.websocket
@pytest.mark.parametrize("url", [
    f"{APP_WS}?numero=",          # vacío
    f"{APP_WS}?numero=abc",       # sin dígitos
    APP_WS,                       # parámetro obligatorio ausente
])
def test_e01_android_connection_with_invalid_number_is_rejected(client, cm_mod, url):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(url):
            pass
    assert cm_mod.manager.active_connections == {}


@pytest.mark.integration
@pytest.mark.websocket
def test_e01_android_registers_and_cleans_up_normalized_number(client, cm_mod):
    with client.websocket_connect(f"{APP_WS}?numero={DESTINO_URLENC}") as ws:
        assert DESTINO in cm_mod.manager.active_connections
        ws.send_text("ping")
        assert ws.receive_text() == "pong"
    assert wait_until(lambda: DESTINO not in cm_mod.manager.active_connections)


# ============================================================================
# E02 / E03  FALLOS DEL WEBHOOK
# ============================================================================
# E02 (Twilio no establece la llamada): no aplica al backend; si Twilio no
# invoca el webhook no ocurre nada en el servidor.

@pytest.mark.integration
@pytest.mark.twilio
def test_e03_webhook_without_destination_fails_and_starts_no_stream(client, monkeypatch):
    monkeypatch.delenv("VISHGUARD_DESTINO", raising=False)
    response = client.post(VOICE_ENDPOINT, data=twilio_form())
    assert response.status_code == 500
    assert "<Stream" not in response.text


# ============================================================================
# E04  AUDIO SIN DESTINO RESUELTO
# ============================================================================

@pytest.mark.integration
@pytest.mark.websocket
def test_e04_audio_without_destination_is_analyzed_but_not_sent(client, fakes, fake_manager):
    with client.websocket_connect(TWILIO_WS) as ws:
        ws.send_json(ev_start(destino=None))
        send_audio(ws, FRAMES_3S)
        finish_call(ws)

    assert len(fakes.analyzer.calls) == 1
    assert fake_manager.sent == []


# ============================================================================
# E05  TIMEOUT SIN AUDIO  (NO IMPLEMENTADO)
# ============================================================================

@pytest.mark.skip(reason="No implementado: no hay timeout por inactividad de audio.")
def test_e05_audio_timeout_is_detected():
    ...


# ============================================================================
# E06  BASE64 INVÁLIDO
# ============================================================================

@pytest.mark.integration
@pytest.mark.websocket
def test_e06_invalid_base64_frame_is_dropped_and_stream_survives(client, fakes, fake_manager):
    with client.websocket_connect(TWILIO_WS) as ws:
        ws.send_json(ev_start())
        ws.send_json({"event": "media", "media": {"payload": "%%%NO_BASE64%%%"}})
        ws.send_json({"event": "media", "media": {"payload": "A"}})  # padding inválido
        send_audio(ws, FRAMES_3S)
        finish_call(ws)

    # Los frames corruptos no aportaron bytes: el chunk sigue siendo de 3 s exactos.
    assert fakes.stt.calls == [CHUNK_BYTES]
    assert len(fake_manager.sent) == 1


# ============================================================================
# E07 / E16  REMANENTE AL RECIBIR STOP
# ============================================================================

@pytest.mark.integration
@pytest.mark.websocket
def test_e07_remainder_below_minimum_is_not_transcribed(client, fakes, fake_manager):
    frames = (MIN_REMANENTE_BYTES // PCM_BYTES_POR_FRAME) - 1  # < 0.5 s
    with client.websocket_connect(TWILIO_WS) as ws:
        ws.send_json(ev_start())
        send_audio(ws, frames)
        finish_call(ws)

    assert fakes.stt.calls == []
    assert fake_manager.sent == []


@pytest.mark.integration
@pytest.mark.websocket
def test_e16_remainder_above_minimum_is_processed_at_stop(client, fakes, fake_manager):
    frames = 50  # 16,000 bytes = 1 s: no llena el chunk, pero supera el mínimo
    with client.websocket_connect(TWILIO_WS) as ws:
        ws.send_json(ev_start())
        send_audio(ws, frames)
        finish_call(ws)

    assert fakes.stt.calls == [frames * PCM_BYTES_POR_FRAME]
    assert len(fake_manager.sent) == 1


# ============================================================================
# E08 / E09 / E10  FALLOS Y VACÍOS EN LA CANALIZACIÓN
# ============================================================================

@pytest.mark.integration
@pytest.mark.websocket
def test_e08_transcription_failure_does_not_break_the_call(client, fakes, fake_manager):
    fakes.stt.behaviors[0] = RuntimeError("STT unavailable")  # falla el 1er chunk
    with client.websocket_connect(TWILIO_WS) as ws:
        ws.send_json(ev_start())
        send_audio(ws, FRAMES_3S * 2)
        finish_call(ws)

    assert len(fakes.stt.calls) == 2
    assert len(fakes.analyzer.calls) == 1       # solo el 2º chunk llegó al análisis
    assert len(fake_manager.sent) == 1


@pytest.mark.integration
@pytest.mark.websocket
def test_e09_empty_transcription_is_not_analyzed(client, fakes, fake_manager):
    fakes.stt.behaviors[0] = ""
    with client.websocket_connect(TWILIO_WS) as ws:
        ws.send_json(ev_start())
        send_audio(ws, FRAMES_3S)
        finish_call(ws)

    assert len(fakes.stt.calls) == 1
    assert fakes.analyzer.calls == []
    assert fake_manager.sent == []
    assert fakes.persist.rows == []


@pytest.mark.integration
@pytest.mark.websocket
def test_e10_analyzer_failure_is_captured_and_stream_continues(client, fakes, fake_manager):
    fakes.analyzer.behaviors[0] = RuntimeError("VishingAnalyzer unavailable")
    with client.websocket_connect(TWILIO_WS) as ws:
        ws.send_json(ev_start())
        send_audio(ws, FRAMES_3S * 2)
        finish_call(ws)

    assert len(fakes.analyzer.calls) == 2
    assert len(fake_manager.sent) == 1          # solo el 2º resultado se envió
    assert len(fakes.persist.rows) == 1


# ============================================================================
# E11 / E12  PERSISTENCIA (core/alert_service.py)
# ============================================================================

class FakeSession:
    def __init__(self, fail_commit: bool = False) -> None:
        self.added: List[Any] = []
        self.committed = False
        self.rolled_back = False
        self.closed = False
        self.fail_commit = fail_commit

    def add(self, row) -> None:
        self.added.append(row)

    def commit(self) -> None:
        if self.fail_commit:
            raise RuntimeError("AlertHistory DB unavailable")
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


class FakeRow:
    def __init__(self, **kwargs) -> None:
        self.__dict__.update(kwargs)


@pytest.fixture
def fake_db(monkeypatch, alert_service_mod):
    state = SimpleNamespace(session=FakeSession(), opened=0)

    def factory():
        state.opened += 1
        return state.session

    monkeypatch.setattr(alert_service_mod, "SessionLocal", factory)
    monkeypatch.setattr(alert_service_mod, "AlertHistory", FakeRow)
    return state


@pytest.mark.unit
@pytest.mark.parametrize("nivel", ["BAJO", "SEGURO", "", None])
def test_e11_low_risk_does_not_generate_alert(alert_service_mod, fake_db, nivel):
    assert alert_service_mod.guardar_alerta_si_aplica({"nivel_riesgo": nivel, "score": 0.1}) is False
    assert fake_db.opened == 0  # ni siquiera abre sesión


@pytest.mark.unit
@pytest.mark.parametrize("nivel", ["MEDIO", "PELIGROSO", "FRAUDE"])
def test_alert_is_saved_with_all_fields(alert_service_mod, fake_db, nivel):
    evaluacion = {
        "nivel_riesgo": nivel,
        "score": 0.8,
        "patrones_detectados": ["urgencia", "clave"],
        "frase_critica": "clave bancaria",
        "recomendacion": "Cuelgue",
    }
    assert alert_service_mod.guardar_alerta_si_aplica(evaluacion) is True

    fila = fake_db.session.added[0]
    assert fila.nivel_riesgo == nivel
    assert fila.score == 0.8
    assert fila.patrones_detectados == "urgencia, clave"
    assert fila.frase_critica == "clave bancaria"
    assert fila.recomendacion == "Cuelgue"
    assert fake_db.session.committed and fake_db.session.closed


@pytest.mark.unit
def test_alert_tolerates_missing_optional_fields(alert_service_mod, fake_db):
    assert alert_service_mod.guardar_alerta_si_aplica({"nivel_riesgo": "MEDIO"}) is True
    fila = fake_db.session.added[0]
    assert fila.score == 0
    assert fila.patrones_detectados == ""


@pytest.mark.unit
def test_e12_db_failure_rolls_back_closes_and_returns_false(alert_service_mod, fake_db):
    fake_db.session.fail_commit = True
    ok = alert_service_mod.guardar_alerta_si_aplica({"nivel_riesgo": "FRAUDE", "score": 0.99})

    assert ok is False
    assert fake_db.session.rolled_back is True
    assert fake_db.session.closed is True


@pytest.mark.integration
@pytest.mark.websocket
def test_e12_persistence_failure_does_not_prevent_alert_delivery(client, fakes, fake_manager):
    """Detectada != persistida: la app recibe la alerta aunque la DB falle."""
    fakes.persist.fail = True
    with client.websocket_connect(TWILIO_WS) as ws:
        ws.send_json(ev_start())
        send_audio(ws, FRAMES_3S)
        finish_call(ws)

    assert len(fake_manager.sent) == 1
    assert fakes.persist.rows == []


@pytest.mark.integration
@pytest.mark.websocket
def test_simulated_stt_sends_to_app_but_never_persists(client, fakes, fake_manager, monkeypatch, twilio_stream_mod):
    monkeypatch.setattr(twilio_stream_mod, "STT_MODE", "simulado")
    with client.websocket_connect(TWILIO_WS) as ws:
        ws.send_json(ev_start())
        send_audio(ws, FRAMES_3S)
        finish_call(ws)

    assert len(fake_manager.sent) == 1
    assert fakes.persist.rows == []


@pytest.mark.integration
@pytest.mark.websocket
def test_low_risk_result_is_still_delivered_to_the_app(client, fakes, fake_manager):
    fakes.analyzer.default = {"nivel_riesgo": "BAJO", "score": 0.1}
    with client.websocket_connect(TWILIO_WS) as ws:
        ws.send_json(ev_start())
        send_audio(ws, FRAMES_3S)
        finish_call(ws)

    assert fake_manager.sent[0][1]["nivel_riesgo"] == "BAJO"


# ============================================================================
# E13  DEDUPLICACIÓN  (NO IMPLEMENTADO)
# ============================================================================

@pytest.mark.skip(reason="No implementado: cada chunk de 3 s con riesgo alto genera "
                         "su propio registro; no hay deduplicación por llamada.")
def test_e13_duplicate_alert_is_deduplicated():
    ...


# ============================================================================
# E14  COLGAR DURANTE EL ANÁLISIS / E15 SIN `stop`
# ============================================================================

@pytest.mark.integration
@pytest.mark.websocket
def test_e14_abrupt_hangup_still_completes_pending_analysis(client, fakes, fake_manager):
    fakes.stt.delay = 0.3
    with client.websocket_connect(TWILIO_WS) as ws:
        ws.send_json(ev_start())
        send_audio(ws, FRAMES_3S)
        # sin `stop`: el cliente se desconecta mientras el análisis sigue en curso

    assert wait_until(lambda: len(fake_manager.sent) == 1)
    assert len(fakes.persist.rows) == 1


@pytest.mark.skip(reason="No implementado: sin `stop` ni desconexión no hay timeout "
                         "que cierre la sesión (solo se cubre la desconexión abrupta).")
def test_e15_missing_stop_event_is_closed_by_timeout():
    ...


# ============================================================================
# E17  DOS LLAMADAS SIMULTÁNEAS
# ============================================================================

@pytest.mark.integration
@pytest.mark.websocket
def test_e17_two_simultaneous_calls_keep_buffers_and_destinations_separate(client, fakes, fake_manager):
    destino_a, destino_b = "+50250000001", "+50250000002"

    with client.websocket_connect(TWILIO_WS) as a, client.websocket_connect(TWILIO_WS) as b:
        a.send_json(ev_start(destino_a))
        b.send_json(ev_start(destino_b))
        send_audio(a, 100)           # remanente (32,000 bytes) -> se procesa al stop
        send_audio(b, FRAMES_3S)     # chunk completo (48,000 bytes)
        finish_call(a)
        finish_call(b)

    assert sorted(fakes.stt.calls) == [100 * PCM_BYTES_POR_FRAME, CHUNK_BYTES]
    assert sorted(n for n, _ in fake_manager.sent) == [destino_a, destino_b]


# ============================================================================
# E18  SEGURIDAD DE LOS WEBSOCKETS
# ============================================================================

@pytest.mark.integration
@pytest.mark.websocket
@pytest.mark.security
def test_e18_app_ws_requires_valid_token_when_auth_enabled(client, stream_mod, monkeypatch):
    monkeypatch.setattr(stream_mod, "WS_AUTH_REQUIRED", True)
    monkeypatch.setattr(stream_mod, "usuario_id_desde_token", lambda t: 7 if t == "good" else None)

    for url in (
        f"{APP_WS}?numero={DESTINO_URLENC}",                 # sin token
        f"{APP_WS}?numero={DESTINO_URLENC}&token=bad",       # token inválido
    ):
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(url):
                pass

    with client.websocket_connect(f"{APP_WS}?numero={DESTINO_URLENC}&token=good") as ws:
        ws.send_text("ping")
        assert ws.receive_text() == "pong"


@pytest.mark.integration
@pytest.mark.security
def test_debug_endpoint_is_disabled_by_default(client):
    assert client.get("/debug/connections").status_code == 404


@pytest.mark.integration
@pytest.mark.security
def test_debug_endpoint_masks_phone_numbers_when_enabled(client, monkeypatch):
    monkeypatch.setenv("VISHGUARD_DEBUG", "1")
    with client.websocket_connect(f"{APP_WS}?numero={DESTINO_URLENC}"):
        response = client.get("/debug/connections")

    assert response.status_code == 200
    cuerpo = response.json()
    assert cuerpo["total"] == 1
    assert cuerpo["conectados"] == ["***8032"]
    assert DESTINO not in response.text


# ============================================================================
# E19  EVENTOS / JSON DESCONOCIDOS
# ============================================================================

@pytest.mark.integration
@pytest.mark.websocket
def test_e19_unknown_events_and_invalid_json_are_ignored(client, fakes, fake_manager):
    with client.websocket_connect(TWILIO_WS) as ws:
        ws.send_json(ev_start())
        ws.send_text("esto no es json")
        ws.send_json({"event": "mark", "mark": {"name": "x"}})
        ws.send_json({"event": "dtmf", "dtmf": {"digit": "1"}})
        ws.send_json({"event": "evento_inventado"})
        ws.send_json({"event": "media", "media": {}})  # sin payload
        send_audio(ws, FRAMES_3S)
        finish_call(ws)

    assert fakes.stt.calls == [CHUNK_BYTES]
    assert len(fake_manager.sent) == 1


# ============================================================================
# E20  AUTENTICACIÓN JWT (core/ws_auth.py)
# ============================================================================

@pytest.fixture
def jwt_env(monkeypatch, ws_auth_mod):
    jwt = pytest.importorskip("jwt")
    security = importlib.import_module("core.security")
    config = importlib.import_module("core.config")

    def make_token(sub="7", exp_delta=300) -> str:
        payload = {"sub": sub, "exp": int(time.time()) + exp_delta}
        return jwt.encode(payload, config.settings.SECRET_KEY, algorithm=security.ALGORITHM)

    class FakeDBSession:
        def __init__(self, user):
            self.user = user

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get(self, model, pk):
            return self.user

    def use_user(user):
        monkeypatch.setattr(ws_auth_mod, "Session", lambda engine: FakeDBSession(user))

    return SimpleNamespace(make_token=make_token, use_user=use_user)


@pytest.mark.unit
@pytest.mark.security
@pytest.mark.parametrize("token", [None, "", "no.es.un.jwt"])
def test_e20_missing_or_garbage_token_returns_none(ws_auth_mod, jwt_env, token):
    assert ws_auth_mod.usuario_id_desde_token(token) is None


@pytest.mark.unit
@pytest.mark.security
def test_e20_expired_token_returns_none(ws_auth_mod, jwt_env):
    jwt_env.use_user(SimpleNamespace(id=7, is_active=True))
    assert ws_auth_mod.usuario_id_desde_token(jwt_env.make_token(exp_delta=-60)) is None


@pytest.mark.unit
@pytest.mark.security
def test_e20_non_numeric_subject_returns_none(ws_auth_mod, jwt_env):
    jwt_env.use_user(SimpleNamespace(id=7, is_active=True))
    assert ws_auth_mod.usuario_id_desde_token(jwt_env.make_token(sub="abc")) is None


@pytest.mark.unit
@pytest.mark.security
def test_e20_unknown_user_returns_none(ws_auth_mod, jwt_env):
    jwt_env.use_user(None)
    assert ws_auth_mod.usuario_id_desde_token(jwt_env.make_token()) is None


@pytest.mark.unit
@pytest.mark.security
def test_e20_inactive_user_returns_none(ws_auth_mod, jwt_env):
    jwt_env.use_user(SimpleNamespace(id=7, is_active=False))
    assert ws_auth_mod.usuario_id_desde_token(jwt_env.make_token()) is None


@pytest.mark.unit
@pytest.mark.security
def test_e20_valid_token_returns_user_id(ws_auth_mod, jwt_env):
    jwt_env.use_user(SimpleNamespace(id=7, is_active=True))
    assert ws_auth_mod.usuario_id_desde_token(jwt_env.make_token()) == 7


# ============================================================================
# ConnectionManager (unitarias)
# ============================================================================

@pytest.mark.unit
@pytest.mark.parametrize("entrada, esperado", [
    (" 50257008032", DESTINO),        # '+' convertido en espacio por la query string
    ("+502 5700-8032", DESTINO),
    ("+50257008032", DESTINO),
    ("", ""),
    (None, ""),
    ("abc", ""),
])
def test_manager_normalizar(cm_mod, entrada, esperado):
    assert cm_mod.ConnectionManager.normalizar(entrada) == esperado


@pytest.mark.unit
def test_manager_connect_normalizes_key_and_accepts(cm_mod):
    manager, ws = cm_mod.ConnectionManager(), FakeWS()
    clave = asyncio.run(manager.connect(ws, " 50257008032"))

    assert clave == DESTINO
    assert ws.accepted is True
    assert manager.active_connections[DESTINO] is ws


@pytest.mark.unit
def test_manager_reconnect_replaces_and_closes_previous_socket(cm_mod):
    manager, viejo, nuevo = cm_mod.ConnectionManager(), FakeWS(), FakeWS()

    async def escenario():
        await manager.connect(viejo, DESTINO)
        await manager.connect(nuevo, DESTINO)

    asyncio.run(escenario())
    assert manager.active_connections[DESTINO] is nuevo
    assert viejo.closed is True


@pytest.mark.unit
def test_manager_late_disconnect_of_old_socket_keeps_new_one(cm_mod):
    manager, viejo, nuevo = cm_mod.ConnectionManager(), FakeWS(), FakeWS()

    async def escenario():
        await manager.connect(viejo, DESTINO)
        await manager.connect(nuevo, DESTINO)

    asyncio.run(escenario())
    manager.disconnect(DESTINO, viejo)           # el handler viejo termina tarde
    assert manager.active_connections[DESTINO] is nuevo

    manager.disconnect(DESTINO, nuevo)
    assert DESTINO not in manager.active_connections


@pytest.mark.unit
def test_manager_enviar_a_delivers_json(cm_mod):
    manager, ws = cm_mod.ConnectionManager(), FakeWS()

    async def escenario():
        await manager.connect(ws, DESTINO)
        return await manager.enviar_a(DESTINO, {"x": 1})

    assert asyncio.run(escenario()) is True
    assert ws.sent == [{"x": 1}]


@pytest.mark.unit
def test_manager_enviar_a_unknown_number_returns_false(cm_mod):
    manager = cm_mod.ConnectionManager()
    assert asyncio.run(manager.enviar_a(DESTINO, {"x": 1})) is False


@pytest.mark.unit
def test_manager_enviar_a_dead_socket_returns_false_and_is_removed(cm_mod):
    manager, ws = cm_mod.ConnectionManager(), FakeWS(fail_send=True)

    async def escenario():
        await manager.connect(ws, DESTINO)
        return await manager.enviar_a(DESTINO, {"x": 1})

    assert asyncio.run(escenario()) is False
    assert DESTINO not in manager.active_connections


# ============================================================================
# GRABACIÓN OPCIONAL DEL AUDIO (WAV) Y PUNTOS DE EXTENSIÓN
# ============================================================================

import re  # noqa: E402
import wave  # noqa: E402


@pytest.fixture
def grabar(monkeypatch, tmp_path):
    """Activa la grabación WAV en una carpeta temporal y devuelve esa carpeta."""
    carpeta = tmp_path / "rec"
    monkeypatch.setenv("VISHGUARD_GUARDAR_WAV", "1")
    monkeypatch.setenv("VISHGUARD_WAV_DIR", str(carpeta))
    return carpeta


def leer_wav(ruta):
    with wave.open(str(ruta), "rb") as w:
        n = w.getnframes()
        return SimpleNamespace(
            canales=w.getnchannels(),
            ancho=w.getsampwidth(),
            hz=w.getframerate(),
            frames=n,
            datos=w.readframes(n),
        )


def canales_wav(datos: bytes):
    """Separa un WAV estéreo de 16 bits en (canal izquierdo, canal derecho)."""
    import audioop

    return audioop.tomono(datos, 2, 1, 0), audioop.tomono(datos, 2, 0, 1)


def frames_si_valido(ruta):
    """Muestras del WAV, o None si el archivo aún no está cerrado/legible."""
    try:
        return leer_wav(ruta).frames
    except (wave.Error, EOFError, OSError):
        return None


@pytest.mark.integration
@pytest.mark.websocket
def test_wav_is_disabled_by_default_and_creates_nothing(client, fakes, fake_manager, monkeypatch, tmp_path):
    carpeta = tmp_path / "rec"
    monkeypatch.delenv("VISHGUARD_GUARDAR_WAV", raising=False)
    monkeypatch.setenv("VISHGUARD_WAV_DIR", str(carpeta))
    with client.websocket_connect(TWILIO_WS) as ws:
        ws.send_json(ev_start())
        send_audio(ws, FRAMES_3S)
        finish_call(ws)

    assert not carpeta.exists()
    assert fakes.stt.calls == [CHUNK_BYTES]


@pytest.mark.integration
@pytest.mark.websocket
def test_wav_is_saved_with_the_pipeline_format(client, fakes, fake_manager, grabar):
    with client.websocket_connect(TWILIO_WS) as ws:
        ws.send_json(ev_start())
        send_audio(ws, FRAMES_3S)
        finish_call(ws)

    archivos = list(grabar.glob("*.wav"))
    assert len(archivos) == 1
    assert archivos[0].name.startswith(CALL_SID + "_")

    wav = leer_wav(archivos[0])
    assert (wav.canales, wav.ancho, wav.hz) == (2, 2, 8000)       # PCM16 estéreo 8 kHz
    assert wav.frames == FRAMES_3S * MULAW_BYTES_POR_FRAME        # 24,000 muestras = 3 s
    assert fakes.stt.calls == [CHUNK_BYTES]                       # grabar no altera la canalización


@pytest.mark.integration
@pytest.mark.websocket
def test_wav_content_equals_the_decoded_audio(client, fakes, fake_manager, grabar):
    import audioop
    import base64

    mulaw = bytes([0x10, 0x30, 0x50, 0x70] * 40)  # 160 bytes con señal (no silencio)
    payload = base64.b64encode(mulaw).decode()
    with client.websocket_connect(TWILIO_WS) as ws:
        ws.send_json(ev_start())
        for _ in range(5):
            ws.send_json({"event": "media", "media": {"payload": payload}})
        finish_call(ws)

    archivo = next(grabar.glob("*.wav"))
    izq, der = canales_wav(leer_wav(archivo).datos)
    assert izq == audioop.ulaw2lin(mulaw, 2) * 5      # sin `track`: se asume el llamante (canal izquierdo)
    assert der == bytes(len(izq))                     # nadie habló por el canal derecho


@pytest.mark.integration
@pytest.mark.websocket
@pytest.mark.security
def test_wav_filename_is_sanitized_against_path_traversal(client, fakes, fake_manager, grabar, tmp_path):
    inicio = ev_start()
    inicio["start"]["callSid"] = "../../evil"
    with client.websocket_connect(TWILIO_WS) as ws:
        ws.send_json(inicio)
        send_audio(ws, 5)
        finish_call(ws)

    archivos = list(tmp_path.rglob("*.wav"))
    assert len(archivos) == 1
    assert archivos[0].parent == grabar                        # no escapó de la carpeta
    assert re.fullmatch(r"evil_\d{8}_\d{6}_[0-9a-f]{4}\.wav", archivos[0].name)


@pytest.mark.integration
@pytest.mark.websocket
def test_wav_skips_invalid_base64_frames(client, fakes, fake_manager, grabar):
    with client.websocket_connect(TWILIO_WS) as ws:
        ws.send_json(ev_start())
        ws.send_json({"event": "media", "media": {"payload": "%%%NO_BASE64%%%"}})
        send_audio(ws, FRAMES_3S)
        finish_call(ws)

    assert leer_wav(next(grabar.glob("*.wav"))).frames == FRAMES_3S * MULAW_BYTES_POR_FRAME


@pytest.mark.integration
@pytest.mark.websocket
def test_wav_is_valid_after_an_abrupt_hangup(client, fakes, fake_manager, grabar):
    with client.websocket_connect(TWILIO_WS) as ws:
        ws.send_json(ev_start())
        send_audio(ws, 50)
        # sin `stop`: el WAV debe cerrarse igual y quedar legible

    esperado = 50 * MULAW_BYTES_POR_FRAME
    assert wait_until(lambda: any(frames_si_valido(p) == esperado for p in grabar.glob("*.wav")))


@pytest.mark.integration
@pytest.mark.websocket
def test_wav_failure_never_interrupts_the_call(client, fakes, fake_manager, monkeypatch, tmp_path):
    no_es_carpeta = tmp_path / "no_es_carpeta"
    no_es_carpeta.write_text("x")                              # un archivo donde debería ir la carpeta
    monkeypatch.setenv("VISHGUARD_GUARDAR_WAV", "1")
    monkeypatch.setenv("VISHGUARD_WAV_DIR", str(no_es_carpeta))
    with client.websocket_connect(TWILIO_WS) as ws:
        ws.send_json(ev_start())
        send_audio(ws, FRAMES_3S)
        finish_call(ws)

    assert fakes.stt.calls == [CHUNK_BYTES]                    # la llamada se procesó igual
    assert len(fake_manager.sent) == 1
    assert no_es_carpeta.read_text() == "x"


@pytest.mark.integration
@pytest.mark.websocket
def test_wav_cap_stops_recording_but_not_the_analysis(client, fakes, fake_manager, grabar, monkeypatch, twilio_stream_mod):
    monkeypatch.setattr(twilio_stream_mod, "WAV_MAX_BYTES", 16_000)  # 1 s
    with client.websocket_connect(TWILIO_WS) as ws:
        ws.send_json(ev_start())
        send_audio(ws, FRAMES_3S)
        finish_call(ws)

    assert leer_wav(next(grabar.glob("*.wav"))).frames == 8_000      # solo 1 s grabado
    assert fakes.stt.calls == [CHUNK_BYTES]                          # el análisis recibió los 3 s


@pytest.mark.unit
def test_recorder_disabled_is_a_safe_noop(twilio_stream_mod, monkeypatch):
    monkeypatch.delenv("VISHGUARD_GUARDAR_WAV", raising=False)
    grabador = twilio_stream_mod.GrabadorWav("CA1")
    grabador.escribir("inbound", b"\x00" * 320, 0)
    grabador.cerrar()
    grabador.cerrar()
    assert grabador.ruta is None


@pytest.mark.integration
@pytest.mark.websocket
def test_analysis_stage_is_a_single_replaceable_seam(client, fakes, fake_manager, monkeypatch, twilio_stream_mod):
    """Contrato para añadir después un interruptor del análisis: basta con
    sustituir `_etapa_analisis`; transcripción, notificación y el resto no cambian."""

    async def neutro(texto: str) -> dict:
        return {"nivel_riesgo": "BAJO", "score": 0, "texto": texto}

    monkeypatch.setattr(twilio_stream_mod, "_etapa_analisis", neutro)
    with client.websocket_connect(TWILIO_WS) as ws:
        ws.send_json(ev_start())
        send_audio(ws, FRAMES_3S)
        finish_call(ws)

    assert fakes.analyzer.calls == []                                # el analizador no se tocó
    assert fake_manager.sent[0][1]["texto"] == fakes.stt.default_text


# ============================================================================
# CONVERSACIÓN COMPLETA: AMBOS LADOS (both_tracks), CADA MENSAJE IDENTIFICADO
# ============================================================================
# inbound  = quien LLAMA   -> hablante "llamante"
# outbound = quien RECIBE  -> hablante "receptor"

BYTE_LLAMANTE = 0x10   # "voz" sintética del llamante (no es silencio)
BYTE_RECEPTOR = 0x90   # "voz" sintética del receptor (decodifica a un valor distinto)


def decodificado(byte: int, frames: int) -> bytes:
    """PCM16 que debe resultar de `frames` frames mu-law con ese byte."""
    import audioop

    return audioop.ulaw2lin(bytes([byte] * MULAW_BYTES_POR_FRAME), 2) * frames


def quien_habla(pcm: bytes) -> str:
    """Texto de prueba según el audio recibido: distingue a cada hablante."""
    voz = decodificado(BYTE_LLAMANTE, 1)[:2]
    return "habla el llamante" if pcm[:2] == voz else "habla el receptor"


def send_conversacion(ws, frames: int, ini_llamante: int = 0, ini_receptor: int = 0) -> None:
    """Intercala los frames de ambos lados, como los envía Twilio con both_tracks."""
    for i in range(frames):
        ws.send_json(ev_media("inbound", ini_llamante + 20 * i, BYTE_LLAMANTE))
        ws.send_json(ev_media("outbound", ini_receptor + 20 * i, BYTE_RECEPTOR))


@pytest.mark.integration
@pytest.mark.twilio
def test_twiml_without_caller_number_only_sends_the_receiver_parameter(client):
    """Sin `From` (p. ej. al probar desde Swagger) no se envía el parámetro `from`."""
    response = client.post(VOICE_ENDPOINT)
    assert response.status_code == 200
    stream = parse_twiml(response).find("Start/Stream")
    assert {p.attrib["name"] for p in stream.findall("Parameter")} == {"to"}


@pytest.mark.integration
@pytest.mark.websocket
def test_both_tracks_are_transcribed_and_labeled_by_speaker(client, fakes, fake_manager):
    fakes.stt.clasificar = quien_habla
    with client.websocket_connect(TWILIO_WS) as ws:
        ws.send_json(ev_start(llamante=LLAMANTE))
        send_conversacion(ws, FRAMES_3S, ini_llamante=100, ini_receptor=220)
        finish_call(ws)

    assert fakes.stt.calls == [CHUNK_BYTES, CHUNK_BYTES]            # un bloque por hablante
    assert all(numero == DESTINO for numero, _ in fake_manager.sent)
    mensajes = {m["hablante"]: m for _, m in fake_manager.sent}
    assert set(mensajes) == {"llamante", "receptor"}
    assert mensajes["llamante"]["texto"] == "habla el llamante"
    assert mensajes["receptor"]["texto"] == "habla el receptor"
    assert mensajes["llamante"]["inicio_ms"] == 100                 # primer frame de su bloque
    assert mensajes["receptor"]["inicio_ms"] == 220
    assert mensajes["llamante"]["nivel_riesgo"] == "PELIGROSO"      # el resultado del analizador se conserva


@pytest.mark.integration
@pytest.mark.websocket
def test_track_field_missing_is_treated_as_the_caller(client, fakes, fake_manager):
    with client.websocket_connect(TWILIO_WS) as ws:
        ws.send_json(ev_start())
        send_audio(ws, FRAMES_3S)  # frames sin campo `track`
        finish_call(ws)

    assert [m["hablante"] for _, m in fake_manager.sent] == ["llamante"]


@pytest.mark.integration
@pytest.mark.websocket
def test_unknown_track_is_ignored(client, fakes, fake_manager):
    with client.websocket_connect(TWILIO_WS) as ws:
        ws.send_json(ev_start())
        send_audio(ws, FRAMES_3S, pista="otra_pista")
        finish_call(ws)

    assert fakes.stt.calls == []
    assert fake_manager.sent == []


@pytest.mark.integration
@pytest.mark.websocket
def test_each_speaker_has_its_own_buffer_and_remainder(client, fakes, fake_manager):
    fakes.stt.clasificar = quien_habla
    with client.websocket_connect(TWILIO_WS) as ws:
        ws.send_json(ev_start())
        send_audio(ws, 100, "inbound", 0, BYTE_LLAMANTE)     # 32,000 bytes
        send_audio(ws, 60, "outbound", 0, BYTE_RECEPTOR)     # 19,200 bytes
        finish_call(ws)

    assert sorted(fakes.stt.calls) == [60 * PCM_BYTES_POR_FRAME, 100 * PCM_BYTES_POR_FRAME]
    assert {m["hablante"] for _, m in fake_manager.sent} == {"llamante", "receptor"}


@pytest.mark.integration
@pytest.mark.websocket
def test_a_short_remainder_of_one_speaker_does_not_affect_the_other(client, fakes, fake_manager):
    fakes.stt.clasificar = quien_habla
    with client.websocket_connect(TWILIO_WS) as ws:
        ws.send_json(ev_start())
        send_audio(ws, 100, "inbound", 0, BYTE_LLAMANTE)
        send_audio(ws, 10, "outbound", 0, BYTE_RECEPTOR)     # 3,200 bytes: bajo el mínimo (0.5 s)
        finish_call(ws)

    assert fakes.stt.calls == [100 * PCM_BYTES_POR_FRAME]
    assert [m["hablante"] for _, m in fake_manager.sent] == ["llamante"]


@pytest.mark.integration
@pytest.mark.websocket
def test_speakers_are_processed_in_parallel_not_one_after_the_other(client, fakes, fake_manager):
    """Con un solo lock, dos hablantes con un STT lento acumularían retraso."""
    fakes.stt.delay = 0.3
    fakes.stt.clasificar = quien_habla
    with client.websocket_connect(TWILIO_WS) as ws:
        ws.send_json(ev_start())
        send_conversacion(ws, FRAMES_3S)
        finish_call(ws)

    assert fakes.stt.max_concurrentes == 2
    assert len(fake_manager.sent) == 2


@pytest.mark.integration
@pytest.mark.websocket
def test_wav_has_one_channel_per_speaker(client, fakes, fake_manager, grabar):
    with client.websocket_connect(TWILIO_WS) as ws:
        ws.send_json(ev_start(llamante=LLAMANTE))
        send_conversacion(ws, 50)
        finish_call(ws)

    wav = leer_wav(next(grabar.glob("*.wav")))
    assert (wav.canales, wav.ancho, wav.hz) == (2, 2, 8000)
    izq, der = canales_wav(wav.datos)
    assert izq == decodificado(BYTE_LLAMANTE, 50)     # canal izquierdo = llamante
    assert der == decodificado(BYTE_RECEPTOR, 50)     # canal derecho  = receptor


@pytest.mark.integration
@pytest.mark.websocket
def test_wav_aligns_both_speakers_by_timestamp(client, fakes, fake_manager, grabar):
    """El receptor contesta 1 s después: su canal arranca con 1 s de silencio."""
    with client.websocket_connect(TWILIO_WS) as ws:
        ws.send_json(ev_start())
        send_audio(ws, 100, "inbound", 0, BYTE_LLAMANTE)       # 0 s -> 2 s
        send_audio(ws, 50, "outbound", 1000, BYTE_RECEPTOR)    # 1 s -> 2 s
        finish_call(ws)

    wav = leer_wav(next(grabar.glob("*.wav")))
    assert wav.frames == 16_000                                # 2 s en total
    izq, der = canales_wav(wav.datos)
    assert izq == decodificado(BYTE_LLAMANTE, 100)
    assert der[:16_000] == bytes(16_000)                       # 1 s de silencio...
    assert der[16_000:] == decodificado(BYTE_RECEPTOR, 50)     # ...y luego su voz


@pytest.mark.integration
@pytest.mark.websocket
def test_wav_mono_mode_mixes_both_speakers(client, fakes, fake_manager, grabar, monkeypatch):
    import audioop

    monkeypatch.setenv("VISHGUARD_WAV_MODO", "mono")
    with client.websocket_connect(TWILIO_WS) as ws:
        ws.send_json(ev_start())
        send_conversacion(ws, 10)
        finish_call(ws)

    wav = leer_wav(next(grabar.glob("*.wav")))
    esperado = audioop.add(
        audioop.mul(decodificado(BYTE_LLAMANTE, 10), 2, 0.5),
        audioop.mul(decodificado(BYTE_RECEPTOR, 10), 2, 0.5),
        2,
    )
    assert (wav.canales, wav.hz) == (1, 8000)
    assert wav.datos == esperado


@pytest.mark.integration
@pytest.mark.websocket
@pytest.mark.security
def test_absurd_timestamp_cannot_make_the_recorder_reserve_memory(client, fakes, fake_manager, grabar):
    """El timestamp llega por un WebSocket sin autenticar: no puede inflar la grabación."""
    with client.websocket_connect(TWILIO_WS) as ws:
        ws.send_json(ev_start())
        ws.send_json(ev_media("inbound", 10**9, BYTE_LLAMANTE))   # ~16 GB de silencio si se rellenara
        send_audio(ws, FRAMES_3S - 1, "inbound", 20, BYTE_LLAMANTE)
        finish_call(ws)

    assert fakes.stt.calls == [CHUNK_BYTES]                       # la llamada se procesa igual
    assert next(grabar.glob("*.wav")).stat().st_size < 100_000    # y la grabación se detuvo


@pytest.mark.unit
def test_recorder_ignores_unknown_tracks_and_bad_timestamps(twilio_stream_mod, grabar):
    grabador = twilio_stream_mod.GrabadorWav("CAx")
    grabador.escribir("pista_rara", b"\x01\x02" * 160, 0)       # pista desconocida: se ignora
    grabador.escribir("inbound", b"\x01\x00" * 160, -5)         # timestamp negativo: se añade sin rellenar
    grabador.cerrar()
    grabador.cerrar()                                            # cerrar dos veces es inocuo

    wav = leer_wav(next(grabar.glob("*.wav")))
    assert wav.frames == 160


# ============================================================================
# MOTORES DE TRANSCRIPCIÓN (modules/stt.py) Y SU CONEXIÓN CON LA LLAMADA
# ============================================================================
# Se prueban con modelos FALSOS: no descargan Whisper ni llaman a Gemini. Lo que se
# comprueba es la conexión: formato del audio, parámetros y elección del motor.


class FakeWhisperModel:
    """Sustituye a faster_whisper.WhisperModel."""

    instancias: List[Any] = []

    def __init__(self, model_size_or_path, device, compute_type):
        self.args = (model_size_or_path, device, compute_type)
        self.llamadas: List[Any] = []
        FakeWhisperModel.instancias.append(self)

    def transcribe(self, audio, **kwargs):
        self.llamadas.append((audio, kwargs))
        segmentos = [SimpleNamespace(text=" hola "), SimpleNamespace(text="mundo ")]
        return iter(segmentos), SimpleNamespace(language="es")  # generador, como el real


class FakeGeminiClient:
    """Sustituye a google.genai.Client."""

    def __init__(self, api_key=None):
        self.api_key = api_key
        self.llamadas: List[Any] = []
        self.fallan: set = set()
        self.models = SimpleNamespace(generate_content=self._generar)

    def _generar(self, model, contents):
        self.llamadas.append((model, contents))
        if model in self.fallan:
            raise RuntimeError("modelo caído")
        return SimpleNamespace(text="  texto de gemini ")


@pytest.fixture
def stt_mod(monkeypatch):
    """modules/stt.py aislado: sin leer el .env real ni variables de Whisper del entorno."""
    modulo = importlib.import_module("modules.stt")
    monkeypatch.setattr(modulo, "load_dotenv", lambda *a, **k: None)
    for variable in ("WHISPER_MODEL", "WHISPER_DEVICE", "WHISPER_COMPUTE"):
        monkeypatch.delenv(variable, raising=False)
    return modulo


@pytest.fixture
def fake_faster_whisper(monkeypatch):
    import sys
    import types

    pytest.importorskip("numpy")
    FakeWhisperModel.instancias.clear()
    falso = types.ModuleType("faster_whisper")
    falso.WhisperModel = FakeWhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", falso)
    return FakeWhisperModel


@pytest.fixture
def fake_gemini(monkeypatch):
    import sys
    import types

    cliente = FakeGeminiClient()
    google = types.ModuleType("google")
    genai = types.ModuleType("google.genai")
    tipos = types.ModuleType("google.genai.types")

    def crear_cliente(api_key=None):
        cliente.api_key = api_key
        return cliente

    genai.Client = crear_cliente
    genai.types = tipos
    tipos.Part = SimpleNamespace(
        from_bytes=lambda data, mime_type: SimpleNamespace(data=data, mime_type=mime_type)
    )
    google.genai = genai
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.genai", genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", tipos)
    monkeypatch.setenv("GEMINI_API_KEY", "clave-de-prueba")
    return cliente


@pytest.mark.unit
def test_pcm8k_a_16k_doubles_the_sample_rate(stt_mod):
    pcm8k = decodificado(BYTE_LLAMANTE, FRAMES_3S)                # 3 s a 8 kHz = 48,000 bytes
    assert abs(len(stt_mod.pcm8k_a_16k(pcm8k)) - 2 * len(pcm8k)) <= 8   # 3 s a 16 kHz


@pytest.mark.unit
def test_whisper_engine_transcribes_a_pcm_block_in_memory(stt_mod, fake_faster_whisper):
    import numpy as np

    motor = stt_mod.SpeechToText()
    modelo = fake_faster_whisper.instancias[0]
    assert modelo.args == ("tiny", "cpu", "int8")                 # los valores de tu rama Pablo

    assert motor.transcribir_pcm(decodificado(BYTE_LLAMANTE, FRAMES_3S)) == "hola mundo"

    audio, opciones = modelo.llamadas[0]
    assert audio.dtype == np.float32 and audio.ndim == 1          # lo que acepta faster-whisper
    assert abs(len(audio) - 48_000) <= 8                          # 3 s a 16 kHz
    assert float(np.abs(audio).max()) <= 1.0                      # normalizado a [-1, 1]
    assert opciones == {"language": "es", "beam_size": 1, "vad_filter": True}


@pytest.mark.unit
def test_whisper_engine_model_is_configurable_by_environment(stt_mod, fake_faster_whisper, monkeypatch):
    monkeypatch.setenv("WHISPER_MODEL", "base")
    monkeypatch.setenv("WHISPER_DEVICE", "cuda")
    monkeypatch.setenv("WHISPER_COMPUTE", "float16")
    stt_mod.SpeechToText()
    assert fake_faster_whisper.instancias[0].args == ("base", "cuda", "float16")


@pytest.mark.unit
def test_whisper_engine_keeps_the_original_file_api(stt_mod, fake_faster_whisper, tmp_path):
    """La API de tu rama Pablo (transcribir_audio(ruta)) sigue funcionando."""
    archivo = tmp_path / "prueba.wav"
    archivo.write_bytes(b"RIFF")
    motor = stt_mod.SpeechToText()
    assert motor.transcribir_audio(str(archivo)) == "hola mundo"
    with pytest.raises(FileNotFoundError):
        motor.transcribir_audio(str(tmp_path / "no_existe.wav"))


@pytest.mark.unit
def test_gemini_service_sends_a_wav_at_the_real_sample_rate(stt_mod, fake_gemini):
    import io as _io
    import wave as _wave

    servicio = stt_mod.SpeechToTextService()
    assert servicio.transcribir_audio_bytes(bytes(3200)) == "texto de gemini"

    modelo, contenido = fake_gemini.llamadas[0]
    assert modelo == "gemini-3.5-flash-lite"
    assert contenido[0].mime_type == "audio/wav"
    with _wave.open(_io.BytesIO(contenido[0].data), "rb") as wav:
        assert (wav.getnchannels(), wav.getframerate()) == (1, 16000)

    servicio.transcribir_audio_bytes(bytes(3200), sample_rate=8000)   # parámetro nuevo
    with _wave.open(_io.BytesIO(fake_gemini.llamadas[1][1][0].data), "rb") as wav:
        assert wav.getframerate() == 8000


@pytest.mark.unit
def test_gemini_service_falls_back_to_the_next_model(stt_mod, fake_gemini):
    fake_gemini.fallan = {"gemini-3.5-flash-lite"}
    assert stt_mod.SpeechToTextService().transcribir_audio_bytes(bytes(3200)) == "texto de gemini"
    assert [m for m, _ in fake_gemini.llamadas] == ["gemini-3.5-flash-lite", "gemini-3.5-flash"]


@pytest.mark.unit
def test_gemini_service_returns_empty_when_every_model_fails(stt_mod, fake_gemini):
    fake_gemini.fallan = {"gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-3.8-flash"}
    assert stt_mod.SpeechToTextService().transcribir_audio_bytes(bytes(3200)) == ""


@pytest.mark.unit
def test_gemini_service_without_api_key_returns_empty(stt_mod, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    servicio = stt_mod.SpeechToTextService()
    assert servicio.client is None
    assert servicio.transcribir_audio_bytes(bytes(3200)) == ""


@pytest.mark.unit
def test_stt_whisper_mode_uses_the_local_engine(monkeypatch, twilio_stream_mod):
    recibido: List[int] = []
    motor = SimpleNamespace(transcribir_pcm=lambda pcm: recibido.append(len(pcm)) or "hola desde whisper")
    monkeypatch.setattr(twilio_stream_mod, "STT_MODE", "whisper")
    monkeypatch.setattr(twilio_stream_mod, "_get_whisper", lambda: motor)

    assert twilio_stream_mod.transcribir_audio(decodificado(BYTE_LLAMANTE, FRAMES_3S)) == "hola desde whisper"
    assert recibido == [CHUNK_BYTES]                              # PCM de 8 kHz tal como llega


@pytest.mark.unit
def test_stt_gemini_mode_receives_audio_converted_to_16khz(monkeypatch, twilio_stream_mod):
    recibido: List[int] = []
    motor = SimpleNamespace(transcribir_audio_bytes=lambda pcm: recibido.append(len(pcm)) or "hola desde gemini")
    monkeypatch.setattr(twilio_stream_mod, "STT_MODE", "gemini")
    monkeypatch.setattr(twilio_stream_mod, "_get_gemini", lambda: motor)

    assert twilio_stream_mod.transcribir_audio(decodificado(BYTE_LLAMANTE, FRAMES_3S)) == "hola desde gemini"
    assert abs(recibido[0] - 2 * CHUNK_BYTES) <= 8                # el doble de bytes: 16 kHz, no 8 kHz


@pytest.mark.unit
@pytest.mark.parametrize("modo, motor", [("whisper", "_get_whisper"), ("gemini", "_get_gemini")])
def test_stt_engines_are_not_used_for_silence(monkeypatch, twilio_stream_mod, modo, motor):
    def no_debe_llamarse():
        raise AssertionError("el motor no debe cargarse ni usarse con silencio")

    monkeypatch.setattr(twilio_stream_mod, "STT_MODE", modo)
    monkeypatch.setattr(twilio_stream_mod, motor, no_debe_llamarse)
    assert twilio_stream_mod.transcribir_audio(decodificado(0xFF, FRAMES_3S)) == ""


@pytest.mark.unit
def test_unknown_stt_mode_returns_empty_and_logs_an_error(monkeypatch, twilio_stream_mod, caplog):
    import logging

    monkeypatch.setattr(twilio_stream_mod, "STT_MODE", "inventado")
    with caplog.at_level(logging.ERROR, logger="vishguard.twilio"):
        assert twilio_stream_mod.transcribir_audio(decodificado(BYTE_LLAMANTE, FRAMES_3S)) == ""
    assert any("desconocido" in r.getMessage() for r in caplog.records)


@pytest.mark.unit
def test_simulated_mode_warns_once_that_nothing_is_transcribed(monkeypatch, twilio_stream_mod, caplog):
    import logging

    monkeypatch.setattr(twilio_stream_mod, "STT_MODE", "simulado")
    monkeypatch.setattr(twilio_stream_mod, "_aviso_stt_emitido", False)
    with caplog.at_level(logging.WARNING, logger="vishguard.twilio"):
        twilio_stream_mod._avisar_modo_stt()
        twilio_stream_mod._avisar_modo_stt()
    avisos = [r for r in caplog.records if "SIMULADO" in r.getMessage()]
    assert len(avisos) == 1                                       # una sola vez por proceso


@pytest.mark.integration
@pytest.mark.websocket
def test_first_call_in_simulated_mode_logs_the_warning(client, fakes, fake_manager, monkeypatch, twilio_stream_mod, caplog):
    import logging

    monkeypatch.setattr(twilio_stream_mod, "STT_MODE", "simulado")
    monkeypatch.setattr(twilio_stream_mod, "_aviso_stt_emitido", False)
    with caplog.at_level(logging.WARNING, logger="vishguard.twilio"):
        with client.websocket_connect(TWILIO_WS) as ws:
            ws.send_json(ev_start())
            finish_call(ws)
    assert any("SIMULADO" in r.getMessage() for r in caplog.records)


@pytest.mark.unit
def test_recorders_without_callsid_in_the_same_second_do_not_overwrite_each_other(twilio_stream_mod, grabar):
    a = twilio_stream_mod.GrabadorWav(None)
    b = twilio_stream_mod.GrabadorWav(None)
    assert a.ruta != b.ruta
    a.escribir("inbound", b"\x01\x00" * 160, 0)
    b.escribir("inbound", b"\x01\x00" * 160, 0)
    a.cerrar()
    b.cerrar()
    assert len(list(grabar.glob("*.wav"))) == 2


@pytest.mark.integration
@pytest.mark.websocket
def test_two_simultaneous_calls_without_callsid_leave_two_recordings(client, fakes, fake_manager, grabar):
    """Reproduce los logs de las 08:49: dos conexiones a la vez, `start` sin callSid."""
    inicio = {"event": "start", "streamSid": "TEST123"}
    with client.websocket_connect(TWILIO_WS) as a, client.websocket_connect(TWILIO_WS) as b:
        a.send_json(inicio)
        b.send_json(inicio)
        send_audio(a, 50)
        send_audio(b, 50)
        finish_call(a)
        finish_call(b)
    assert len(list(grabar.glob("sin_sid_*.wav"))) == 2


# ============================================================================
# LOG DE TEXTO (SOLO PRUEBAS)  -  inicio del bloque
# Cubre VISHGUARD_LOG_TEXTO. Si eliminas esa función de twilio_stream.py,
# borra también este bloque entero (hasta la marca "fin del bloque").
# ============================================================================


def _mensajes_de_texto(caplog) -> List[str]:
    return [r.getMessage() for r in caplog.records if "[TEXTO]" in r.getMessage()]


def _llamada_con_dos_hablantes(client) -> None:
    with client.websocket_connect(TWILIO_WS) as ws:
        ws.send_json(ev_start())
        send_conversacion(ws, FRAMES_3S, ini_llamante=100, ini_receptor=220)
        finish_call(ws)


@pytest.mark.integration
@pytest.mark.websocket
@pytest.mark.security
def test_text_log_is_off_by_default(client, fakes, fake_manager, monkeypatch, caplog):
    import logging

    monkeypatch.delenv("VISHGUARD_LOG_TEXTO", raising=False)
    fakes.stt.clasificar = quien_habla
    with caplog.at_level(logging.INFO, logger="vishguard.twilio"):
        _llamada_con_dos_hablantes(client)

    assert len(fake_manager.sent) == 2                     # la llamada se procesó igual
    assert _mensajes_de_texto(caplog) == []                # pero nada de lo dicho llegó al log
    assert "habla el llamante" not in caplog.text and "habla el receptor" not in caplog.text


@pytest.mark.integration
@pytest.mark.websocket
def test_text_log_prints_who_said_what_when_enabled(client, fakes, fake_manager, monkeypatch, caplog):
    import logging

    monkeypatch.setenv("VISHGUARD_LOG_TEXTO", "1")
    fakes.stt.clasificar = quien_habla
    with caplog.at_level(logging.INFO, logger="vishguard.twilio"):
        _llamada_con_dos_hablantes(client)

    assert sorted(_mensajes_de_texto(caplog)) == [
        "[TEXTO] llamante @ 0.1 s: habla el llamante",
        "[TEXTO] receptor @ 0.2 s: habla el receptor",
    ]


@pytest.mark.integration
@pytest.mark.websocket
def test_text_log_does_not_print_empty_transcriptions(client, fakes, fake_manager, monkeypatch, caplog):
    import logging

    monkeypatch.setenv("VISHGUARD_LOG_TEXTO", "1")
    fakes.stt.behaviors[0] = ""
    with caplog.at_level(logging.INFO, logger="vishguard.twilio"):
        with client.websocket_connect(TWILIO_WS) as ws:
            ws.send_json(ev_start())
            send_audio(ws, FRAMES_3S)
            finish_call(ws)

    assert _mensajes_de_texto(caplog) == []


@pytest.mark.unit
@pytest.mark.security
def test_text_log_warns_once_that_it_is_active(monkeypatch, twilio_stream_mod, caplog):
    import logging

    monkeypatch.setenv("VISHGUARD_LOG_TEXTO", "1")
    monkeypatch.setattr(twilio_stream_mod, "_aviso_stt_emitido", False)
    with caplog.at_level(logging.WARNING, logger="vishguard.twilio"):
        twilio_stream_mod._avisar_modo_stt()
        twilio_stream_mod._avisar_modo_stt()

    assert len([r for r in caplog.records if "VISHGUARD_LOG_TEXTO" in r.getMessage()]) == 1


# LOG DE TEXTO (SOLO PRUEBAS)  -  fin del bloque
# ============================================================================


# ============================================================================
# SMOKE TEST CON LA APP REAL
# ============================================================================

def _rutas_de_la_app(application) -> List[str]:
    """Todas las rutas (HTTP y WebSocket) de una app FastAPI, con prefijos.

    En FastAPI recientes `include_router` ya no aplana las rutas: `app.routes`
    contiene `_IncludedRouter` sin `.path`. Por eso se recorre de forma
    recursiva (con respaldos por si cambia la estructura interna) y además se
    añaden las rutas HTTP que publica OpenAPI.
    """
    rutas: List[str] = []

    def visitar(routes, prefijo: str = "") -> None:
        for ruta in routes:
            path = getattr(ruta, "path", None)
            if path is not None and not hasattr(ruta, "routes"):
                rutas.append(prefijo + path)
                continue
            original = getattr(ruta, "original_router", None)  # _IncludedRouter
            if original is not None:
                contexto = getattr(ruta, "include_context", None)
                visitar(original.routes, prefijo + (getattr(contexto, "prefix", "") or ""))
                continue
            hijas = getattr(ruta, "routes", None)  # Mount / Router clásicos
            if hijas:
                visitar(hijas, prefijo + (path or ""))

    visitar(application.routes)
    try:
        rutas.extend(application.openapi().get("paths", {}).keys())
    except Exception:  # noqa: BLE001 - el esquema OpenAPI es solo un respaldo
        pass
    return sorted(set(rutas))


@pytest.mark.integration
def test_real_app_registers_twilio_and_stream_routes():
    """Detecta el olvido de `include_router` en la app real."""
    modulo = os.getenv("VISHGUARD_APP_MODULE", "main")
    atributo = os.getenv("VISHGUARD_APP_ATTRIBUTE", "app")
    try:
        real_app = getattr(importlib.import_module(modulo), atributo)
    except (ImportError, AttributeError) as exc:
        pytest.skip(f"No se pudo importar {modulo}.{atributo}: {exc}")

    rutas = _rutas_de_la_app(real_app)
    faltan = [
        sufijo
        for sufijo in ("/twilio/voice", "/ws/twilio", "/ws/stream")
        if not any(r.endswith(sufijo) for r in rutas)
    ]
    assert not faltan, (
        f"Rutas ausentes en {modulo}.{atributo}: {faltan}. ¿Falta "
        f"app.include_router(...) en main.py? Rutas registradas: {rutas}"
    )