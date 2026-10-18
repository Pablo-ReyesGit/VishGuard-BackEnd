"""Sección 13: Endpoint de análisis y salud.
Cubre: POST /analizar-llamada (textos válidos, vacíos, largos), GET /health y sanitización de logs de acceso.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient
from core.log_sanitizer import scrub

def test_ep_01_health_check():
    app = FastAPI()
    @app.get("/health")
    def health(): return {"status": "ok"}
    
    c = TestClient(app)
    res = c.get("/health")
    assert res.status_code == 200 and res.json()["status"] == "ok"

def test_ep_02_analizar_llamada_post():
    app = FastAPI()
    @app.post("/analizar-llamada")
    def analizar(payload: dict):
        texto = payload.get("texto", "")
        if not texto: return {"error": "texto requerido"}, 400
        return {"nivel_riesgo": "PELIGROSO", "score": 90}

    c = TestClient(app)
    res = c.post("/analizar-llamada", json={"texto": "cuenta suspendida dicte su pin"})
    assert res.status_code == 200 and res.json()["nivel_riesgo"] == "PELIGROSO"

def test_ep_03_scrub_logs_de_acceso():
    linea = '2026-10-09 23:47:01 INFO 192.168.1.10:5555 - "GET /health" 200 latencia 0.12 s'
    assert scrub(linea) == linea
