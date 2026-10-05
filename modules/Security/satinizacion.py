"""
pii_sanitizer.py
----------------
Implementación del diagrama de actividades "PII_Sanitizer_Activity" (Sheet1).

Flujo:
  1. Recibe texto_transcrito desde Whisper STT.
  2. Inicializa texto_sanitizado = texto_transcrito.
  3. Carga patrones Regex (DNI, Tarjetas, Teléfonos, Emails).
  4. Recorre cada patrón (bucle "Bucle de Regex Matching"):
       - Si hay coincidencia -> reemplaza por [ETIQUETA_PROTEGIDA].
  5. Devuelve texto_sanitizado.
"""

import re
from typing import Dict, Pattern


class PIISanitizer:
    """Sanitiza información personal identificable (PII) de una transcripción."""

    # Patrones Regex (DNI, Tarjetas, Teléfonos, Emails) -> etiqueta protegida
    PATRONES: Dict[str, Pattern] = {
        "DNI": re.compile(r"\b\d{8}[A-Za-z]?\b"),
        "TARJETA": re.compile(r"\b(?:\d[ -]?){13,19}\b"),
        "TELEFONO": re.compile(r"\b(?:\+?\d{1,3}[ -]?)?\d{3}[ -]?\d{3}[ -]?\d{3,4}\b"),
        "EMAIL": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    }

    def sanitizar(self, texto_transcrito: str) -> str:
        """Recibe texto_transcrito desde Whisper STT y retorna texto_sanitizado."""
        texto_sanitizado = texto_transcrito  # Inicializar texto_sanitizado

        # Bucle de Regex Matching: repeat ... while quedan patrones por evaluar
        for nombre_patron, patron in self.PATRONES.items():
            etiqueta = f"[{nombre_patron}_PROTEGIDO]"
            if patron.search(texto_sanitizado):  # ¿Existe coincidencia?
                texto_sanitizado = patron.sub(etiqueta, texto_sanitizado)
            # si no hay coincidencia, continúa con el siguiente patrón

        return texto_sanitizado  # Generar texto_sanitizado final


if __name__ == "__main__":
    sanitizer = PIISanitizer()
    ejemplo = "Mi DNI es 12345678A, mi tarjeta 4111 1111 1111 1111 y mi correo juan@ejemplo.com"
    print(sanitizer.sanitizar(ejemplo))