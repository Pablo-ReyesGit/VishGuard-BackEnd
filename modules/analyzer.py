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
            response = self.client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": self._prompt(texto)}],
                response_format={"type": "json_object"},
                timeout=2.5,  # coincide con tu diagrama del circuit breaker
            )
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            print(f"❌ Falla en Groq, cayendo a heurístico local: {e}")
            return self._evaluacion_local(texto)

    def _evaluacion_local(self, texto: str) -> dict:
        return evaluar_amenaza_como_json(texto)

    def _prompt(self, texto: str) -> str:
        return f"""Actúa como un experto en ciberseguridad..."""  # tu prompt actual