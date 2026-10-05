import os
import json
import re
from google import genai
from dotenv import load_dotenv

load_dotenv()

class VishingAnalyzer:
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            print("⚠️ [ANALYZER]: No se detectó GEMINI_API_KEY en .env")
            self.client = None
        else:
            self.client = genai.Client(api_key=api_key)
            print("🔑 [ANALYZER]: Cliente Gemini inicializado con éxito.")

    def analizar_texto(self, texto: str) -> dict:
        if not self.client:
            return self._evaluacion_local(texto)

        prompt = f"""
Eres un analista experto en ciberseguridad y detección de vishing y extorsión telefónica.
Analiza la siguiente frase de una llamada: "{texto}"

Clasificación:
- BAJO: Saludos o pláticas familiares sin exigencias monetarias ni presiones. Score 0-20.
- MEDIO: Llamadas comerciales sospechosas, confirmación de datos u ofertas dudosas. Score 35-65.
- PELIGROSO: Petición urgente de dinero en efectivo, amenazas policiales/cárcel/accidentes o solicitud de claves/CVV/SMS. Score 80-100.

Responde ÚNICAMENTE un JSON válido con esta estructura exacta sin explicaciones adicionales:
{{"nivel_riesgo": "PELIGROSO", "score": 95, "recomendacion": "..."}}
"""

        # Modelos habilitados en tu cuenta ordenados por velocidad y menor saturación
        modelos = [
            "models/gemini-3.5-flash-lite",
            "models/gemini-3.5-flash",
            "models/gemini-3.8-flash"
        ]

        for mod in modelos:
            try:
                # Invocación directa sin esperas
                response = self.client.models.generate_content(
                    model=mod,
                    contents=prompt
                )

                if response and response.text:
                    raw_text = response.text.strip()
                    if "```" in raw_text:
                        raw_text = re.sub(r"```(json)?", "", raw_text).strip()

                    resultado = json.loads(raw_text)
                    print(f"✨ [ANÁLISIS EXITOSO DE GEMINI - Modelo: {mod}]")
                    return resultado

            except Exception as e:
                print(f"⚠️ {mod} no disponible ({e}). Pasando al siguiente modelo sin demora...")
                continue

        print("❌ [TODOS LOS MODELOS FALLARON]: Activando contingencia heurística.")
        return self._evaluacion_local(texto)

    def _evaluacion_local(self, texto: str) -> dict:
        t = texto.lower()
        extorsion = any(w in t for w in ["policía", "policia", "accidente", "cárcel", "carcel", "atropellé", "atropelle", "dinero", "secuestro"])
        bancario = any(w in t for w in ["tarjeta", "sms", "cvv", "nip", "pin", "clave", "código", "token"])

        if extorsion or bancario:
            return {
                "nivel_riesgo": "PELIGROSO",
                "score": 95,
                "recomendacion": "¡Alerta de Fraude o Extorsión! Mantenga la calma y no entregue dinero ni datos."
            }
        return {
            "nivel_riesgo": "BAJO",
            "score": 10,
            "recomendacion": "Llamada sin indicios de riesgo evidente."
        }