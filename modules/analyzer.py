import json
import os
from dotenv import load_dotenv
from google import genai
from google.genai import types
from services.heuristic_engine import evaluar_amenaza_como_json

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


class VishingAnalyzer:

  def __init__(self):
    load_dotenv()  # Garantiza lectura de variables al instanciar
    self.api_key = os.getenv("GEMINI_API_KEY")

    if self.api_key:
      self.client = genai.Client(api_key=self.api_key)
    else:
      self.client = None

    # Lista de modelos asignados con fallback automático
    self.modelos = [
        "gemini-3.5-flash-lite",
        "gemini-3.5-flash",
        "gemini-3.8-flash",
    ]

  def analizar_texto(self, texto: str) -> dict:
    if not self.client:
      print("⚠️ Sin GEMINI_API_KEY: cayendo a motor heurístico local.")
      return self._evaluacion_local(texto)

    prompt_usuario = f'Analiza la siguiente transcripción de llamada:\n"{texto}"'

    configuracion = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        response_mime_type="application/json",
        temperature=0.2,
        max_output_tokens=500,
    )

    # Intenta cada modelo secuencialmente si alguno llega a fallar o saturarse
    for modelo in self.modelos:
      try:
        response = self.client.models.generate_content(
            model=modelo, contents=prompt_usuario, config=configuracion
        )

        if response.text:
          return json.loads(response.text)

      except Exception as e:
        print(
            f"⚠️ Falló el modelo {modelo}: {e}. Reintentando con el siguiente..."
        )

    print("❌ Todos los modelos de Gemini fallaron. Cayendo a motor local.")
    return self._evaluacion_local(texto)

  def _evaluacion_local(self, texto: str) -> dict:
    return evaluar_amenaza_como_json(texto)