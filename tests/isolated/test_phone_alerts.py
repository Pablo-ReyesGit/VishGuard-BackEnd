"""Ejecutar: python -m unittest discover -s tests/isolated -v.

SQLite en memoria y app mínima: no importa main ni arranca Neon/Twilio.
"""
import os
import unittest
from datetime import timedelta
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

with patch.dict(os.environ, {
    "DATABASE_URL": "sqlite://",
    "SECRET_KEY": "isolated-phone-tests-secret-key-123456789",
    "FIRST_SUPERUSER_PASSWORD": "isolated-admin-password",
}):
    from api.deps import get_current_user, get_db
    from api.routes import alerts, users
    from core import alert_service, security, ws_auth
    from models.alert import Alerta
    from models.user import User


class PhoneAlertTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.owner = User(email="owner@example.com", hashed_password="unused")
        self.other = User(email="other@example.com", hashed_password="unused",
                          phone_number="+50222222222")
        self.session.add_all([self.owner, self.other])
        self.session.commit()
        self.session.refresh(self.owner)
        self.session.refresh(self.other)
        self.app = FastAPI()
        self.app.include_router(users.router, prefix="/api/v1")
        self.app.include_router(alerts.router)
        self.app.dependency_overrides[get_db] = lambda: self.session
        self.app.dependency_overrides[get_current_user] = lambda: self.owner
        self.client = TestClient(self.app)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.session.close)
        self.addCleanup(self.client.close)
        self.addCleanup(patch.stopall)
        patch.object(alert_service, "engine", self.engine).start()
        patch.object(ws_auth, "engine", self.engine).start()

    def profile(self, phone):
        return self.client.patch("/api/v1/users/me", json={"phone_number": phone})

    def risky(self, phone):
        return alert_service.guardar_alerta_si_aplica(
            {"nivel_riesgo": "FRAUDE", "score": 0.8, "texto": "Alerta de prueba"},
            numero_destino=phone,
        )

    def test_profile_normalizes_and_clears_phone(self):
        result = self.profile("+502 (1234) 5678")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["phone_number"], "+50212345678")
        self.assertNotIn("hashed_password", result.json())
        self.assertEqual(self.profile(None).status_code, 200)
        self.assertIsNone(self.owner.phone_number)

    def test_invalid_phone_is_rejected(self):
        for phone in ("12345678", "+00000000", "abc", "+50212", 12345678):
            with self.subTest(phone=phone):
                self.assertEqual(self.profile(phone).status_code, 422)

    def test_duplicate_phone_rolls_back(self):
        self.assertEqual(self.profile("+502 2222-2222").status_code, 409)
        self.assertEqual(self.profile("+50212345678").status_code, 200)
        self.assertEqual(self.other.phone_number, "+50222222222")

    def test_signup_stores_phone_and_rejects_duplicate(self):
        payload = {"email": "new@example.com", "password": "test-password-123",
                   "phone_number": "+502 3333 3333"}
        result = self.client.post("/api/v1/users/signup", json=payload)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["phone_number"], "+50233333333")
        payload["email"] = "another@example.com"
        self.assertEqual(self.client.post("/api/v1/users/signup", json=payload).status_code, 409)

    def test_recipient_selects_owner_and_filters_history(self):
        self.assertTrue(self.risky("+502 2222 2222"))
        row = self.session.exec(select(Alerta)).one()
        self.assertEqual(row.usuario_id, self.other.id)
        self.assertEqual(row.score, 80)
        self.assertEqual(self.client.get("/alerts").json(), [])
        self.app.dependency_overrides[get_current_user] = lambda: self.other
        self.assertEqual(len(self.client.get("/alerts").json()), 1)

    def test_missing_unknown_inactive_recipient_does_not_save(self):
        for phone in (None, "bad", "+50299999999"):
            self.assertFalse(self.risky(phone))
        self.other.is_active = False
        self.session.add(self.other)
        self.session.commit()
        self.assertFalse(self.risky(self.other.phone_number))
        self.assertEqual(self.session.exec(select(Alerta)).all(), [])

    def test_low_risk_does_not_save(self):
        self.assertFalse(alert_service.guardar_alerta_si_aplica(
            {"nivel_riesgo": "BAJO", "score": 0}, numero_destino=self.other.phone_number
        ))
        self.assertEqual(self.session.exec(select(Alerta)).all(), [])

    def test_websocket_checks_phone_ownership(self):
        token = security.create_access_token(self.other.id, timedelta(minutes=5))
        self.assertEqual(ws_auth.usuario_id_desde_token(token, "+502 2222 2222"), self.other.id)
        self.assertIsNone(ws_auth.usuario_id_desde_token(token, "+50299999999"))
        self.assertIsNone(ws_auth.usuario_id_desde_token("invalid", self.other.phone_number))


if __name__ == "__main__":
    unittest.main()
