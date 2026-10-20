"""
Caso de Prueba 8: TC-PROP-BACK-PII
Nombre: Filtrado y anonimización de datos personales (PII) previo al envío a la API del LLM
Tipo: Unitaria / Seguridad
Prioridad: Alta
"""
import pytest
from modules.Security.pii_sanitizer import PIISanitizer

@pytest.mark.unit
@pytest.mark.security
def test_sanitize_credit_card_and_dpi():
    """
    Pasos:
    1. Instanciar PIISanitizer.
    2. Ingestar texto con número de tarjeta de crédito (16 dígitos) y DPI (13 dígitos).
    3. Verificar sustitución por etiquetas enmascaradas.
    """
    sanitizer = PIISanitizer()
    texto_entrada = "Mi tarjeta es 4532-1234-5678-9010 y mi DPI es 1234567890101"
    
    texto_limpio = sanitizer.sanitize(texto_entrada)
    
    # Aserciones: Sustitución de datos sensibles y ausencia de números en claro
    assert "4532-1234-5678-9010" not in texto_limpio
    assert "1234567890101" not in texto_limpio
    assert "[TARJETA]" in texto_limpio or "[TARJETA_PROTEGIDA]" in texto_limpio or "[PII]" in texto_limpio
