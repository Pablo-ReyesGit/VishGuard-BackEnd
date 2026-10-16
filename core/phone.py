import re
from typing import Annotated

from pydantic import BeforeValidator


def normalize_phone(value: str) -> str:
    """Normaliza teléfonos internacionales; no adivina el código de país."""
    if not isinstance(value, str):
        raise ValueError("El teléfono debe ser texto con código de país")
    normalized = re.sub(r"[\s()\-]", "", value)
    if not re.fullmatch(r"\+[1-9][0-9]{7,14}", normalized):
        raise ValueError("Usa un teléfono internacional, por ejemplo +50212345678")
    return normalized


PhoneNumber = Annotated[str, BeforeValidator(normalize_phone)]
