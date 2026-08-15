import os
import time
from dotenv import load_dotenv
from google import genai

load_dotenv()

key = os.getenv("GEMINI_API_KEY")
print(f"🔑 Clave leída: {key[:10] if key else 'NINGUNA'}...")

client = genai.Client(api_key=key)

print("⏳ Esperando 10 segundos para limpiar cualquier Rate Limit anterior...")
time.sleep(10)

try:
    print("🚀 Enviando solicitud a 'gemini-2.0-flash'...")
    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents="Responde únicamente: FUNCIONA"
    )
    print(f"\n✅ ¡ÉXITO TOTAL! Respuesta de Gemini: {response.text.strip()}")
except Exception as e:
    print(f"\n❌ Error: {e}")