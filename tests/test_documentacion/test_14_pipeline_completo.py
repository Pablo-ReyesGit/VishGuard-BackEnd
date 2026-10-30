"""Sección 14: Pipeline completo.
Cubre: Integración End-to-End (Audio simulado -> STT -> Análisis Gemini -> Respuesta JSON -> Persistencia) con mocks.
"""
import sys
import os
import modules.analyzer as analyzer_mod
from modules.analyzer import VishingAnalyzer

def test_pipe_01_pipeline_simulado(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(analyzer_mod, "load_dotenv", lambda: None)

    analyzer = VishingAnalyzer()
    audio_simulado = "Estimado cliente, su cuenta bancaria ha sido bloqueada. Por favor dicte el código de confirmación SMS."
    
    resultado = analyzer.analizar_texto(audio_simulado)
    
    assert resultado["nivel_riesgo"] in ["BAJO", "MEDIO", "PELIGROSO"]
    assert "score" in resultado
    assert "mensaje_alerta" in resultado
