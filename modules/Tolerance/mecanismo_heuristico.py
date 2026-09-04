"""
heuristic_engine.py
--------------------
Implementación del diagrama de actividades "Heuristic_Engine_Activity" (Sheet4).

Flujo:
  1. Recibe texto_sanitizado, lo pasa a minúsculas, score = 0.
  2. Cuenta coincidencias con HIGH_RISK_KEYWORDS (x35) y
     MEDIUM_RISK_KEYWORDS (x15), suma al score.
  3. Limita score a máximo 100.
  4. Clasifica:
       score >= 70 -> ROJO
       score >= 40 -> NARANJA
       score >= 20 -> AMARILLO
       else        -> VERDE
  5. Construye JSON estandarizado de respuesta.
"""

from typing import Dict, List


class HeuristicEngine:
    HIGH_RISK_KEYWORDS: List[str] = [
        "transferencia urgente", "clave de acceso", "código de verificación",
        "bloqueo de cuenta", "orden de captura", "embargo",
    ]
    MEDIUM_RISK_KEYWORDS: List[str] = [
        "premio", "banco", "seguridad social", "reembolso", "impuesto",
    ]

    def analyze(self, texto_sanitizado: str) -> Dict:
        texto = texto_sanitizado.lower()  # Convertir texto a minúsculas
        score = 0  # Inicializar score = 0

        # Evaluación de Reglas
        coincidencias_altas = sum(1 for kw in self.HIGH_RISK_KEYWORDS if kw in texto)
        score += coincidencias_altas * 35

        coincidencias_medias = sum(1 for kw in self.MEDIUM_RISK_KEYWORDS if kw in texto)
        score += coincidencias_medias * 15

        score = min(score, 100)  # Asegurar score máximo de 100

        # Clasificación de Riesgo
        if score >= 70:
            nivel, consejo = "ROJO", "¡Peligro! Colgue inmediatamente"
        elif score >= 40:
            nivel, consejo = "NARANJA", "Alerta: Presión/Urgencia detectada"
        elif score >= 20:
            nivel, consejo = "AMARILLO", "Precaución: Menciones inusuales"
        else:
            nivel, consejo = "VERDE", "Sin señales claras de sospecha"

        # Construir JSON estandarizado de respuesta
        return {
            "score": score,
            "nivel": nivel,
            "consejo": consejo,
            "fuente": "HEURISTICO_LOCAL_FALLBACK",
        }


if __name__ == "__main__":
    engine = HeuristicEngine()
    print(engine.analyze("Necesita hacer una transferencia urgente para evitar el bloqueo de cuenta"))