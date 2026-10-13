"""T2 - Log Sanitizer universal (uvicorn.access, uvicorn.error, tracebacks).

Llamar install_log_sanitizer() en el startup de la app (después de que uvicorn
configure sus handlers). Regla: NUNCA loguear transcripciones en INFO.
"""
import logging
import re

_PATTERNS = [
    (re.compile(r"eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]*"), "[JWT]"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-~+/]+=*"), "Bearer [TOKEN]"),
    (re.compile(r"AIza[0-9A-Za-z_\-]{30,}"), "[API_KEY]"),
    (re.compile(r"\bAQ\.[A-Za-z0-9_\-]{20,}"), "[API_KEY]"),   # formato nuevo de claves de Google
    (re.compile(r"\b(?:sk|gsk|pk)[_\-][A-Za-z0-9_\-]{16,}"), "[API_KEY]"),
    (re.compile(r"(?i)([?&](?:token|ticket|api[_-]?key|key|access_token|password|numero|telefono|phone)=)[^&\s\"']+"), r"\1[MASK]"),
    (re.compile(r"(?i)((?:api[_-]?key|secret|password|authorization)\s*[=:]\s*)[^\s,;\"']+"), r"\1[MASK]"),
    (re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"), "[EMAIL]"),
    (re.compile(r"(?<!\w)\+\d{1,3}[ \-.]?\(?\d{2,4}\)?[ \-.]?\d{3,4}[ \-.]?\d{3,4}(?![\w])"), "[TELEFONO]"),   # con prefijo +
    (re.compile(r"(?<![\w/:.\-])\d{4}[ \-]\d{4}(?![\w:.\-/])"), "[TELEFONO]"),                                  # local 8 dígitos
]

def scrub(text: str) -> str:
    for rx, repl in _PATTERNS:
        text = rx.sub(repl, text)
    return text

class LogSanitizerFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            # Formatear primero y limpiar el resultado: limpiar la plantilla o los args por
            # separado puede romper el formato o dejar pasar secretos partidos entre ambos.
            record.msg = scrub(record.getMessage())
            record.args = ()
            if record.exc_info:  # tracebacks: formatear, limpiar y fijar como texto
                record.exc_text = scrub(logging.Formatter().formatException(record.exc_info))
                record.exc_info = None
            elif record.exc_text:
                record.exc_text = scrub(record.exc_text)
        except Exception:
            record.msg, record.args = "[log suprimido: fallo del sanitizador]", ()
            record.exc_info = record.exc_text = None
        return True

_FILTER = LogSanitizerFilter()

def install_log_sanitizer() -> None:
    names = ["", "uvicorn", "uvicorn.access", "uvicorn.error", "fastapi"]
    for name in names:
        lg = logging.getLogger(name)
        lg.addFilter(_FILTER)
        for h in lg.handlers:  # los handlers no heredan filtros del logger
            if _FILTER not in h.filters:
                h.addFilter(_FILTER)
