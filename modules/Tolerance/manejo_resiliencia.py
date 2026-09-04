"""
resilience_manager.py
-----------------------
Implementación del diagrama de secuencia "Resilience Manager & Circuit Breaker"
(Sheet3).

Flujo (App -> WS -> PII -> RM -> Gemini | fallback Heuristic -> WS -> App):
  1. WS pide a PII sanitizar el texto.
  2. WS llama a RM.execute_analysis_with_fallback(texto_sanitizado).
  3. RM intenta Gemini con timeout=2.5s.
       - Éxito: retorna payload con fuente "IA_GEMINI_FLASH".
       - Timeout / error: cae a HeuristicEngine, fuente "HEURISTICO_LOCAL_FALLBACK".
  4. WS emite la alerta de riesgo al Overlay de la app.
"""

import asyncio
from typing import Awaitable, Callable, Dict

from mecanismo_heuristico import HeuristicEngine

GEMINI_TIMEOUT_SECONDS = 2.5

# Firma esperada de la función que llama a la API real de Gemini Flash:
#   async def gemini_call(texto_sanitizado: str) -> dict: ...
GeminiCaller = Callable[[str], Awaitable[Dict]]


class ResilienceManager:
    def __init__(self, gemini_call: GeminiCaller, heuristic: HeuristicEngine = None):
        self._gemini_call = gemini_call
        self._heuristic = heuristic or HeuristicEngine()

    async def execute_analysis_with_fallback(self, texto_sanitizado: str) -> Dict:
        try:
            # RM -> Gemini: Solicita análisis (Timeout = 2.5s)
            resultado = await asyncio.wait_for(
                self._gemini_call(texto_sanitizado),
                timeout=GEMINI_TIMEOUT_SECONDS,
            )
            # Respuesta exitosa (<= 2.5s)
            resultado["fuente"] = "IA_GEMINI_FLASH"
            return resultado

        except (asyncio.TimeoutError, Exception):
            # Timeout (> 2.5s) o Error de Red -> circuit breaker abre hacia el fallback
            return self._heuristic.analyze(texto_sanitizado)


# --- Ejemplo de integración con FastAPI WebSocket (esqueleto) -------------
"""
from fastapi import FastAPI, WebSocket
from pii_sanitizer import PIISanitizer
from resilience_manager import ResilienceManager

app = FastAPI()
sanitizer = PIISanitizer()

async def gemini_call(texto: str) -> dict:
    # Aquí va la llamada real a la API de Gemini Flash
    ...

rm = ResilienceManager(gemini_call=gemini_call)

@app.websocket("/ws/audio")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    while True:
        raw_bytes = await websocket.receive_bytes()   # Envía ráfaga de audio
        texto_transcrito = whisper_transcribe(raw_bytes)  # tu motor Whisper STT
        texto_sanitizado = sanitizer.sanitizar(texto_transcrito)
        payload = await rm.execute_analysis_with_fallback(texto_sanitizado)
        await websocket.send_json(payload)  # Emite alerta de riesgo al Overlay
"""

if __name__ == "__main__":
    async def gemini_ok(texto: str) -> Dict:
        await asyncio.sleep(0.1)
        return {"score": 80, "nivel": "ROJO", "consejo": "Cuidado, posible fraude"}

    async def gemini_lento(texto: str) -> Dict:
        await asyncio.sleep(5)  # supera el timeout -> dispara el fallback
        return {"score": 10, "nivel": "VERDE"}

    async def demo():
        rm_ok = ResilienceManager(gemini_call=gemini_ok)
        print(await rm_ok.execute_analysis_with_fallback("hola"))

        rm_fallback = ResilienceManager(gemini_call=gemini_lento)
        print(await rm_fallback.execute_analysis_with_fallback(
            "transferencia urgente bloqueo de cuenta"))

    asyncio.run(demo())