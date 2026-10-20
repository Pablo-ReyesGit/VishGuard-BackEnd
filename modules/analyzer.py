"""VishingAnalyzer integrado con Sprint 1-2 (reemplaza al analyzer.py original)."""

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv

from modules.resilience.resilience_manager import ResilienceManager, gemini_llm_call

# Carga explícita de variables de entorno
load_dotenv()

SYSTEM_PROMPT = """
Eres un experto en ciberseguridad enfocado en la prevención de Vishing (estafas telefónicas).

INSTRUCCIÓN CLAVE DE FILTRADO Y DIARIZACIÓN:
El audio recibido contiene la conversación de dos personas:
1. El receptor (usuario del teléfono que se defiende o responde).
2. El emisor/llamante (potencial atacante/estafador).

Tu análisis DEBE enfocar el score de riesgo y las alertas ÚNICAMENTE en lo que dice y exige el EMISOR/LLAMANTE.
Ignora las respuestas, dudas o comentarios breves del receptor del teléfono.

DEBES responder ÚNICAMENTE con un objeto JSON válido usando esta estructura exacta:
{
    "nivel_riesgo": "BAJO" | "MEDIO" | "PELIGROSO",
    "score": <número entero entre 0 y 100>,
    "mensaje_alerta": "<Frase muy concisa sobre lo detectado del llamante (máximo 15 palabras)>",
    "recomendacion": "<Instrucción directa para el usuario (máximo 15 palabras)>"
}

Criterios de evaluación:
- BAJO (Score 0-30): Conversaciones cotidianas o llamadas legítimas.
- MEDIO (Score 31-70): Solicitudes inusuales de verificación, ofertas dudosas o preguntas sospechosas.
- PELIGROSO (Score 71-100): Peticiones de claves, códigos SMS/Tokens, simulación de bancos, urgencia o extorsión.
"""

log = logging.getLogger("vishguard.analyzer")

MODELOS_POR_DEFECTO = ["gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-3.8-flash"]
TIMEOUT_LLM = 2.5


class VishingAnalyzer:

    def __init__(self):
        load_dotenv()
        api_key = os.getenv("GEMINI_API_KEY")
        modelos = [m.strip() for m in os.getenv("GEMINI_MODELS", "").split(",") if m.strip()] or MODELOS_POR_DEFECTO
        if api_key:
            llm_call = gemini_llm_call(
                api_key,
                modelos,
                timeout=TIMEOUT_LLM,
                max_output_tokens=int(os.getenv("GEMINI_MAX_TOKENS", "500")),
            )
        else:
            llm_call = None
            log.warning("Sin GEMINI_API_KEY: análisis solo con el motor heurístico local")
        # Instancia ÚNICA por proceso: el circuit breaker debe compartirse entre llamadas.
        self.manager = ResilienceManager(llm_call, timeout=TIMEOUT_LLM)

    async def analizar_texto_async(self, texto: str) -> dict:
        return await self.manager.analizar(texto)

    def analizar_texto(self, texto: str) -> dict:
        """Compatibilidad con llamadores síncronos (también si hay un event loop activo)."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.manager.analizar(texto))
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, self.manager.analizar(texto)).result()