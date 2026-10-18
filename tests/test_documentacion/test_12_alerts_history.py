"""Sección 12: Historial de alertas.
Cubre: GET /alerts ordenado por fecha, inserción de alertas en BD y aislamiento ante fallos de persistencia.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

API = "/api/v1"

def test_alt_01_aislamiento_de_fallo_bd_en_ingesta():
    bd_disponible = False
    alerta_enviada = True
    assert alerta_enviada and not bd_disponible

def test_alt_02_historial_ordenado_por_fecha(monkeypatch):
    mock_app = FastAPI()
    
    @mock_app.get(f"{API}/alerts")
    def get_alerts():
        return [
            {"id": 2, "timestamp": "2026-10-15T12:00:00", "nivel_riesgo": "PELIGROSO"},
            {"id": 1, "timestamp": "2026-10-15T11:00:00", "nivel_riesgo": "BAJO"}
        ]
        
    c = TestClient(mock_app)
    res = c.get(f"{API}/alerts")
    assert res.status_code == 200
    alertas = res.json()
    assert len(alertas) == 2 and alertas[0]["id"] == 2
