"""T1 - Sanitizador y anonimizador PII (fail-closed, bidireccional).

Uso:
    san = PIISanitizer()
    limpio = san.sanitize(texto)            # entrada al LLM
    salida = san.sanitize_output(dict_llm)  # salida del LLM
Si algo falla lanza SanitizationError: el llamador DEBE NO enviar nada al LLM.
"""
import re

class SanitizationError(Exception):
    """El sanitizador falló o dejó residuos: bloquear el envío al LLM."""

_DIGIT_WORDS = {
    "cero": "0", "uno": "1", "una": "1", "dos": "2", "tres": "3", "cuatro": "4",
    "cinco": "5", "seis": "6", "siete": "7", "ocho": "8", "nueve": "9",
}
_DW = "|".join(_DIGIT_WORDS)

# Orden importa: lo más específico primero.
_RE_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_RE_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:[ \-]?[A-Z0-9]{4}){2,7}(?:[ \-]?[A-Z0-9]{1,4})?\b")
_SEP = r"[\s,.\-]{0,2}"
_RE_CARD     = re.compile(rf"(?<!\d)\d(?:{_SEP}\d){{12,18}}(?!\d)")
_RE_NUMS     = re.compile(rf"(?<!\d)\d(?:{_SEP}\d){{6,}}(?!\d)")
_RE_RESIDUAL = re.compile(rf"(?<!\d)\d(?:{_SEP}\d){{8,}}|[\w.+-]+@[\w-]+\.\w+")
_RE_SECRET = re.compile(
    r"(?i)\b(pin|nip|cvv|cvc|clave|contrase[nñ]a|c[oó]digo|token)\b([^\d\n]{0,25})(\d[\d \-]{2,9}\d|\d{3,10})"
)
_RE_WORDS_SEQ = re.compile(rf"(?i)\b(?:(?:{_DW})\b[\s,.\-]*){{4,}}")
_RE_PHONE = re.compile(r"(?<!\d)\+?\d{1,3}?[ \-.]?\(?\d{2,4}\)?[ \-.]?\d{3,4}[ \-.]?\d{3,4}(?!\d)")
# 7+ dígitos aunque vengan separados por espacios, guiones o puntos (DPI, teléfonos locales, folios)
_RE_NUMS = re.compile(r"(?<!\d)\d(?:[ \-.]?\d){6,}(?!\d)")
_RE_URL = re.compile(r"(?i)\b(?:https?://|www\.)\S+")
_RE_RESIDUAL = re.compile(r"(?<!\d)\d(?:[ \-.]?\d){8,}|[\w.+-]+@[\w-]+\.\w+")

def luhn_ok(digits: str) -> bool:
    d = [int(c) for c in digits if c.isdigit()]
    if not 13 <= len(d) <= 19:
        return False
    total = 0
    for i, n in enumerate(reversed(d)):
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0

def iban_ok(raw: str) -> bool:
    s = re.sub(r"[ \-]", "", raw).upper()
    if not 15 <= len(s) <= 34:
        return False
    s = s[4:] + s[:4]
    num = "".join(str(int(c, 36)) for c in s)
    return int(num) % 97 == 1

def mask_urls(text: str) -> str:
    return _RE_URL.sub("[ENLACE]", text)


class PIISanitizer:
    def sanitize(self, text: str) -> str:
        if not isinstance(text, str):
            raise SanitizationError("entrada no es str")
        try:
            out = text
            out = _RE_EMAIL.sub("[EMAIL]", out)
            out = _RE_IBAN.sub(lambda m: "[IBAN]" if iban_ok(m.group()) else m.group(), out)
            out = _RE_CARD.sub(lambda m: "[TARJETA]" if luhn_ok(m.group()) else m.group(), out)
            # PIN/CVV/código dictado ("mi pin es 4821"): conserva la palabra clave (la usa el heurístico)
            out = _RE_SECRET.sub(lambda m: f"{m.group(1)}{m.group(2)}[SECRETO]", out)
            out = _RE_WORDS_SEQ.sub("[NUMERO_DICTADO] ", out)
            out = _RE_PHONE.sub("[TELEFONO]", out)
            out = _RE_NUMS.sub("[DOCUMENTO]", out)
            # Verificación final: si queda algo con forma de PII, bloquear (fail-closed)
            if _RE_RESIDUAL.search(out):
                raise SanitizationError("residuos de PII tras sanitizar")
            return out.strip()
        except SanitizationError:
            raise
        except Exception as exc:  # cualquier fallo = bloqueo
            raise SanitizationError(f"fallo del sanitizador: {type(exc).__name__}") from None

    def sanitize_output(self, data):
        """Sanitiza recursivamente strings de la respuesta del LLM antes de entregarla."""
        if isinstance(data, str):
            return self.sanitize(data)
        if isinstance(data, dict):
            return {k: self.sanitize_output(v) for k, v in data.items()}
        if isinstance(data, list):
            return [self.sanitize_output(v) for v in data]
        return data
