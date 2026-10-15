"""VishingAnalyzer integrado con Sprint 1-2 (reemplaza al analyzer.py original).

Qué cambia frente al original:
  * T1  el texto se sanitiza (PII, fail-closed) ANTES de salir hacia Gemini
  * T8  timeout total 2.5 s, transcripción delimitada (anti prompt injection) y esquema validado
  * T7  piso max(score_LLM, score_heurístico); el nivel sale del score final
  * sin print(): logging (el LogSanitizer cubre uvicorn; un print() se salta el filtro)
  * respuesta con el mismo contrato en TODAS las rutas: nivel_riesgo, score, mensaje_alerta, recomendacion
    (antes la ruta local devolvía patrones_detectados/frase_critica y no mensaje_alerta)
API: `await analyzer.analizar_texto_async(texto)` (preferida). `analizar_texto(texto)` se mantiene
síncrona por compatibilidad; bloquea hasta 2.5 s como máximo (antes podía bloquear sin límite).
"""
import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv

from modules.resilience.resilience_manager import ResilienceManager, gemini_llm_call

log = logging.getLogger("vishguard.analyzer")

MODELOS_POR_DEFECTO = ["gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-3.8-flash"]
TIMEOUT_LLM = 2.5


class VishingAnalyzer:

    def __init__(self):
        load_dotenv()
        api_key = os.getenv("GEMINI_API_KEY")
        modelos = [m.strip() for m in os.getenv("GEMINI_MODELS", "").split(",") if m.strip()] or MODELOS_POR_DEFECTO
        if api_key:
            llm_call = gemini_llm_call(api_key, modelos, timeout=TIMEOUT_LLM)
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
