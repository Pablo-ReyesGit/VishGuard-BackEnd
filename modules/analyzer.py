import json
import os
from groq import Groq

from services.heuristic_engine import evaluar_amenaza_como_json

class VishingAnalyzer:
    def __init__(self):
        api_key = os.getenv("GROQ_API_KEY")
        self.client = Groq(api_key=api_key) if api_key else None
        if not self.client:
            print("⚠️ Sin GROQ_API_KEY: operando solo con motor heurístico local.")

    def analizar_texto(self, texto: str) -> dict:
        if not self.client:
            return self._evaluacion_local(texto)
        try:
            # 👈 Separar el rol 'system' del rol 'user' garantiza la estructura JSON
            response = self.client.chat.completions.create(
                model="qwen/qwen3.6-27b",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Eres un sistema de ciberseguridad. Tu salida DEBE ser exclusivamente "
                            "un objeto JSON válido sin texto adicional ni bloques Markdown."
                        )
                    },
                    {
                        "role": "user",
                        "content": self._prompt(texto)
                    }
                ],
                response_format={"type": "json_object"},
                max_tokens=250,
                temperature=0.1,
                timeout=5.0,
            )
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            print(f"❌ Falla en Groq, cayendo a heurístico local: {e}")
            return self._evaluacion_local(texto)

    def _evaluacion_local(self, texto: str) -> dict:
        return evaluar_amenaza_como_json(texto)

    def _prompt(self, texto: str) -> str:
        return f"""
Analiza si la siguiente frase representa un intento de vishing (estafa telefónica).
Responde en JSON con la siguiente estructura exacta:
{{
    "nivel_riesgo": "BAJO",
    "score": 0,
    "recomendacion": "Instrucción concisa",
    "mensaje_alerta": "Resumen breve"
}}

Reglas:
1. nivel_riesgo debe ser: "BAJO", "MEDIO" o "PELIGROSO".
2. score debe ser un entero de 0 a 100.
3. recomendacion y mensaje_alerta deben ser breves.

Frase: "{texto}"
"""