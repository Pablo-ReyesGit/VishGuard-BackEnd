"""Sección 7: Respaldo ante fallo de la IA.
Cubre: Ausencia de GEMINI_API_KEY, fallback entre modelos en cascada, manejo de timeouts y caída limpia hacia el motor heurístico local.
"""
import asyncio
import json
import pytest
import modules.analyzer as analyzer_mod
from modules.resilience import resilience_manager as rm

CONTRATO = {"nivel_riesgo", "score", "mensaje_alerta", "recomendacion"}
PELIGRO = "Soy del banco BBVA, cuenta suspendida, dígame su pin"

def test_fb_01_sin_api_key_usa_solo_motor_local(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(analyzer_mod, "load_dotenv", lambda: None)
    r = analyzer_mod.VishingAnalyzer().analizar_texto(PELIGRO)
    assert set(r) == CONTRATO and r["nivel_riesgo"] == "PELIGROSO"

def test_fb_02_fallback_al_siguiente_modelo(monkeypatch):
    class _Resp:
        def __init__(self, text): self.text = text
    class _Models:
        def generate_content(self, model, contents, config):
            if model == "m1": raise RuntimeError("429 Too Many Requests")
            return _Resp(json.dumps({"nivel_riesgo": "BAJO", "score": 10, "mensaje_alerta": "ok", "recomendacion": "ok"}))
    class _Client:
        def __init__(self, api_key=None, **k): self.models = _Models()
    
    from google import genai
    monkeypatch.setattr(genai, "Client", _Client)
    
    call = rm.gemini_llm_call("k", ["m1", "m2"], timeout=2.0)
    res = json.loads(asyncio.run(call("s", "u")))
    assert res["score"] == 10

def test_fb_03_caida_a_local_si_todos_los_modelos_fallan(monkeypatch):
    class _Models:
        def generate_content(self, model, contents, config):
            raise RuntimeError("Error general de API")
    class _Client:
        def __init__(self, api_key=None, **k): self.models = _Models()
    
    from google import genai
    monkeypatch.setattr(genai, "Client", _Client)
    
    call = rm.gemini_llm_call("k", ["m1", "m2"], timeout=2.0)
    r = asyncio.run(rm.ResilienceManager(call).analizar(PELIGRO))
    assert r["nivel_riesgo"] == "PELIGROSO" and set(r) == CONTRATO
