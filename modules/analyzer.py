import os
import json
<<<<<<< HEAD
from dotenv import load_dotenv
from groq import Groq
=======
import re
from google import genai
from dotenv import load_dotenv
>>>>>>> b89c59e (feat: integracion de API Gemini funcionando en analyzer)

load_dotenv()

class VishingAnalyzer:
    def __init__(self):
<<<<<<< HEAD
        api_key = os.getenv("GROQ_API_KEY")
        if api_key:
            self.client = Groq(api_key=api_key)
        else:
            self.client = None
            print("⚠️ ADVERTENCIA: No se encontró GROQ_API_KEY en el entorno.")
=======
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            print("⚠️ [ANALYZER]: No se detectó GEMINI_API_KEY en .env")
            self.client = None
        else:
            self.client = genai.Client(api_key=api_key)
            print("🔑 [ANALYZER]: Cliente Gemini inicializado con éxito.")
>>>>>>> b89c59e (feat: integracion de API Gemini funcionando en analyzer)

    def analizar_texto(self, texto: str) -> dict:
        if not self.client:
            return self._evaluacion_local(texto)

        prompt = f"""
<<<<<<< HEAD
        Actúa como un experto en ciberseguridad especializado en detección de Vishing (estafas telefónicas).
        
        Analiza la intención, el contexto semántico y el nivel de ingeniería social del siguiente texto transcrito de una llamada:
        
        "{texto}"
        
        Responde ÚNICAMENTE con un objeto JSON válido con esta estructura exacta sin formato markdown adicional:
        {{
            "nivel_riesgo": "PELIGROSO" | "MEDIO" | "BAJO",
            "score": <número entero entre 0 y 100>,
            "patrones_detectados": ["patrón o táctica detectada 1", "patrón 2"],
            "frase_critica": "frase transcrita más sospechosa",
            "recomendacion": "instrucción directa de seguridad para el usuario"
        }}
        """

        try:
            # Usamos el modelo Llama 3.3 70B en formato JSON
            response = self.client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            
            contenido = response.choices[0].message.content
            return json.loads(contenido)
            
        except Exception as e:
            print(f"❌ Error al consultar la API de Groq: {e}")
            return self._evaluacion_local(texto)

    def _evaluacion_local(self, texto: str) -> dict:
        return {
            "nivel_riesgo": "MEDIO",
            "score": 50,
            "patrones_detectados": ["Evaluación local de respaldo"],
            "frase_critica": texto[:80],
            "recomendacion": "Precaución: Mantenga la alerta con llamadas desconocidas."
=======
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
>>>>>>> b89c59e (feat: integracion de API Gemini funcionando en analyzer)
        }