"""Comprueba el arranque y el contrato Android contra SQLite temporal.

Ejecutar desde la raíz: python tests/isolated/smoke_full_app.py
Se ejecuta en un proceso separado para aislar la configuración de main.
"""
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

with TemporaryDirectory(prefix="vishguard-smoke-") as directory:
    os.environ.update({
        "DATABASE_URL": "sqlite:///" + (Path(directory) / "test.db").as_posix(),
        "SECRET_KEY": "full-app-smoke-key-for-local-tests-only",
        "FIRST_SUPERUSER_PASSWORD": "smoke-test-admin-password",
        "GEMINI_API_KEY": "",
        "VISHGUARD_STT": "simulado",
        "VISHGUARD_GUARDAR_WAV": "0",
        "VISHGUARD_LOG_TEXTO": "0",
        "WS_AUTH_REQUIRED": "true",
    })
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect
    from core.alert_service import guardar_alerta_si_aplica
    from core.connection_manager import manager
    from database import engine
    from main import app

    try:
        with TestClient(app) as client:
            assert client.get("/").status_code == 200
            phone = "+50212345678"
            created = client.post("/api/v1/users/signup", json={
                "email": "smoke@example.com", "password": "smoke-account-password",
                "phone_number": phone,
            })
            assert created.status_code == 200, "Signup failed"
            login = client.post("/api/v1/login/access-token", data={
                "username": "smoke@example.com", "password": "smoke-account-password",
            })
            assert login.status_code == 200, "Login failed"
            token = login.json()["access_token"]
            headers = {"Authorization": "Bearer " + token}
            assert client.get("/api/v1/users/me", headers=headers).json()["phone_number"] == phone
            evaluation = {
                "nivel_riesgo": "PELIGROSO", "score": 90,
                "mensaje_alerta": "Alerta de prueba local", "recomendacion": "Verifica la llamada",
            }
            assert guardar_alerta_si_aplica(evaluation, numero_destino=phone)
            history = client.get("/alerts", headers=headers)
            assert history.status_code == 200 and len(history.json()) == 1
            assert history.json()[0]["mensaje_alerta"] == evaluation["mensaje_alerta"]
            with client.websocket_connect("/ws/stream", params={"numero": phone, "token": token}) as socket:
                socket.send_text("ping")
                assert socket.receive_text() == "pong"
                assert client.portal.call(manager.enviar_a, phone, evaluation)
                assert socket.receive_json()["score"] == 90
            try:
                with client.websocket_connect("/ws/stream", params={
                    "numero": "+50299999999", "token": token,
                }):
                    raise AssertionError("WebSocket accepted a different user's phone")
            except WebSocketDisconnect as exc:
                assert exc.code == 1008
            analysis = client.post("/analizar-llamada", json={"texto": "Hola, buenos dias"},
                                   headers=headers)
            assert analysis.status_code == 200
            assert 0 <= analysis.json()["score"] <= 100
            assert analysis.json()["es_simulacion"] and analysis.json()["alerta_guardada"]
            history = client.get("/alerts", headers=headers).json()
            assert len(history) == 2
            assert any(item["id"] == analysis.json()["alerta_id"] and item["es_simulacion"]
                       for item in history)
            assert client.post("/analizar-llamada", json={"texto": "Prueba"}).status_code == 401
        print("OK: startup, signup, login, profile, persistence, history, WebSocket and analysis")
        print("Database used: temporary SQLite. No calls to Neon, Twilio or Gemini.")
    finally:
        engine.dispose()
