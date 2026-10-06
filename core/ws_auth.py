from typing import Optional

import jwt
from jwt.exceptions import InvalidTokenError
from pydantic import ValidationError
from sqlmodel import Session

from core import security
from core.config import settings
from database import engine
from models.user import User
from schemas.token import TokenPayload


def usuario_id_desde_token(token: Optional[str]) -> Optional[int]:
    """Valida un JWT (misma lógica que deps.get_current_user) y devuelve el
    id del usuario activo, o None si el token no sirve.

    Función SÍNCRONA: desde código async usar `asyncio.to_thread`.
    """
    if not token:
        return None
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[security.ALGORITHM]
        )
        data = TokenPayload(**payload)
    except (InvalidTokenError, ValidationError):
        return None

    if data.sub is None or not str(data.sub).isdigit():
        return None

    with Session(engine) as session:
        user = session.get(User, int(data.sub))
        if user is None or not user.is_active:
            return None
        return user.id