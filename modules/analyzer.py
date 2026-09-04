import os
import json
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

class VishingAnalyzer:
    def __init__(self):
        api_key = os.getenv("GROQ_API_KEY")
        if api_key:
            self.client = Groq(api_key=api_key)
        else:
            self.client = None
            print("⚠️ ADVERTENCIA: No se encontró GROQ_API_KEY en el entorno.")

    def analizar_texto(self, texto: str) -> dict:
        if not self.client:
            return self._evaluacion_local(texto)

        prompt = f"""
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
        }