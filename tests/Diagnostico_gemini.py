"""Diagnóstico de Gemini para VishGuard. Ejecutar desde la raíz del backend:  python diagnostico_gemini.py
Lee GEMINI_API_KEY / GEMINI_MODELS / GEMINI_MAX_TOKENS del .env. No imprime la clave ni transcripciones reales."""
import asyncio
import os
import time

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()
key = os.getenv("GEMINI_API_KEY")
modelos = [m.strip() for m in os.getenv("GEMINI_MODELS", "").split(",") if m.strip()] or \
    ["gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-3.8-flash"]
max_tokens = int(os.getenv("GEMINI_MAX_TOKENS", "500"))
if not key:
    raise SystemExit("No hay GEMINI_API_KEY en el entorno/.env")

from modules.resilience.resilience_manager import (SYSTEM_PROMPT, LLMResult, ResilienceManager,
                                                   build_user_prompt, gemini_llm_call)

TEXTO = "Buenas tardes, le habla el departamento de seguridad del banco. Su cuenta fue suspendida, necesito que me dicte su pin ahora mismo."

def mostrar(e):
    return f"{type(e).__name__} code={getattr(e,'code',None)} status={getattr(e,'status',None)} msg={str(getattr(e,'message',e))[:250]}"

client = genai.Client(api_key=key)
print("== A) Prompt REAL del analizador, 1 modelo a la vez, SDK directo (sin mi adaptador) ==")
cfg = types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT, response_mime_type="application/json",
                                  temperature=0.2, max_output_tokens=max_tokens)
for m in modelos:
    t0 = time.monotonic()
    try:
        r = client.models.generate_content(model=m, contents=build_user_prompt(TEXTO), config=cfg)
        u = r.usage_metadata
        fin = r.candidates[0].finish_reason if r.candidates else None
        try:
            LLMResult.model_validate_json(r.text or ""); valido = "JSON VÁLIDO"
        except Exception:
            valido = "JSON INVÁLIDO/TRUNCADO"
        print(f"  {m}: {time.monotonic()-t0:.2f}s finish={fin} tokens_salida={getattr(u,'candidates_token_count',None)} "
              f"tokens_razonamiento={getattr(u,'thoughts_token_count',None)} -> {valido}")
        if valido != "JSON VÁLIDO": print("     texto recibido:", repr((r.text or "")[:150]))
    except Exception as e:
        print(f"  {m}: FALLÓ -> {mostrar(e)}")

print("\n== B) Mi adaptador + ResilienceManager completo (lo que corre en producción) ==")
async def main():
    for m in modelos:
        mgr = ResilienceManager(gemini_llm_call(key, [m], timeout=2.5, max_output_tokens=max_tokens), timeout=2.5)
        t0 = time.monotonic()
        r = await mgr.analizar(TEXTO)
        usado = "LLM" if mgr.breaker.failures == 0 else "SOLO LOCAL (el LLM falló: mira el WARNING de arriba)"
        print(f"  {m}: {time.monotonic()-t0:.2f}s nivel={r['nivel_riesgo']} score={r['score']} -> {usado}")
asyncio.run(main())