"""Sección 5: Analizador de fraude (IA Gemini Flash).
Cubre: Análisis de oraciones legítimas, sospechosas y fraudulentas; respuestas JSON estructuradas y Pydantic.
"""
import sys
import os
import json
import asyncio

import modules.analyzer as analyzer_mod
from modules.analyzer import VishingAnalyzer

def test_ia_01_casos_de_prueba_estaticos(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(analyzer_mod, "load_dotenv", lambda: None)
    
    analyzer = VishingAnalyzer()
    
    r1 = analyzer.analizar_texto("Hola buenas tardes, le llamamos de la clinica medica para confirmarle su cita de manana.")
    assert set(r1) == {"nivel_riesgo", "score", "mensaje_alerta", "recomendacion"}
    
    r3 = analyzer.analizar_texto("Le habla el ingeniero de seguridad del banco. Necesito que me dicte el codigo SMS de 6 digitos.")
    assert r3["nivel_riesgo"] == "PELIGROSO"

def test_ia_02_analizar_texto_sincrono_con_event_loop_activo(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(analyzer_mod, "load_dotenv", lambda: None)
    a = VishingAnalyzer()
    
    async def desde_endpoint_async():
        return a.analizar_texto("cuenta suspendida, dicte su pin")
        
    res = asyncio.run(desde_endpoint_async())
    assert res["nivel_riesgo"] == "PELIGROSO"

def test_ia_03_modelos_configurables_por_entorno(monkeypatch):
    capt = {}
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("GEMINI_MODELS", " m1 , m2 ")
    monkeypatch.setattr(analyzer_mod, "load_dotenv", lambda: None)
    monkeypatch.setattr(analyzer_mod, "gemini_llm_call", lambda k, modelos, **kw: capt.update(m=modelos))
    VishingAnalyzer()
    assert capt["m"] == ["m1", "m2"]
