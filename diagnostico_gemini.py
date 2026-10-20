"""Diagnóstico de Gemini para VishGuard: ¿por qué responde 400?  Ejecutar desde la raíz del backend:
    python diagnostico_gemini.py
Lee GEMINI_API_KEY (y GEMINI_MODELS si existe) del .env. NO imprime la clave ni transcripciones."""
import os
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()
key = os.getenv("GEMINI_API_KEY")
modelos = [m.strip() for m in os.getenv("GEMINI_MODELS", "").split(",") if m.strip()] or \
    ["gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-3.8-flash"]
if not key:
    raise SystemExit("No hay GEMINI_API_KEY en el entorno/.env")
print(f"Clave cargada: {len(key)} caracteres, empieza por {key[:4]}... (no se muestra completa)")

def mostrar(e):
    return f"{type(e).__name__} code={getattr(e,'code',None)} status={getattr(e,'status',None)} msg={str(getattr(e,'message',e))[:250]}"

# 1) ¿La clave es válida y qué modelos existen? (si falla aquí, el problema es la CLAVE, no el código)
client = genai.Client(api_key=key)
try:
    disponibles = sorted(m.name.removeprefix("models/") for m in client.models.list())
    print(f"1) Clave válida. {len(disponibles)} modelos visibles. Gemini flash:",
          [m for m in disponibles if "flash" in m][:12])
    for m in modelos:
        print(f"   - {m}: {'EXISTE' if m in disponibles else 'NO EXISTE para esta clave'}")
except Exception as e:
    print("1) FALLÓ listar modelos ->", mostrar(e))

# 2) Llamada mínima como el analizador original (sin http_options)
for m in modelos:
    try:
        r = client.models.generate_content(model=m, contents='Responde solo {"ok": true}',
            config=types.GenerateContentConfig(response_mime_type="application/json", max_output_tokens=50))
        print(f"2) {m}: OK -> {r.text!r}")
    except Exception as e:
        print(f"2) {m}: FALLÓ ->", mostrar(e))
