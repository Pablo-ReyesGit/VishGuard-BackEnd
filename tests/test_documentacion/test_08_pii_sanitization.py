"""Sección 8: Sanitización de PII.
Cubre: PIISanitizer (fail-closed), algoritmo de Luhn para tarjetas, DPI, teléfono, emails, PIN dictado y sanitización recursiva de JSONs.
"""
import pytest
from modules.Security.pii_sanitizer import PIISanitizer, SanitizationError, luhn_ok

S = PIISanitizer()

def test_pii_01_entrada_no_string_bloquea():
    with pytest.raises(SanitizationError):
        S.sanitize(None)

def test_pii_02_tarjeta_luhn_se_enmascara():
    assert luhn_ok("4539148803436467")
    assert "[TARJETA]" in S.sanitize("tarjeta 4539 1488 0343 6467")

def test_pii_03_correo_iban_y_pin_no_salen_en_claro():
    out = S.sanitize("iban ES9121000418450200051332 correo juan@mail.com mi pin es 4821")
    assert "ES91" not in out and "juan@mail.com" not in out and "4821" not in out

def test_pii_04_numeros_dictados_se_enmascaran():
    out = S.sanitize("mi cuenta es uno dos tres cuatro cinco seis")
    assert "uno dos" not in out

def test_pii_05_salida_llm_se_sanitiza_recursivamente():
    out = S.sanitize_output({"mensaje_alerta": "correo a@b.co y pin 4821", "items": ["llama +502 5555 1234"]})
    assert "a@b.co" not in out["mensaje_alerta"] and "4821" not in out["mensaje_alerta"]
    assert "+502 5555 1234" not in out["items"][0]
