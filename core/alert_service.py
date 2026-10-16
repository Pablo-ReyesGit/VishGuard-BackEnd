import logging

from sqlmodel import Session, select

from database import engine
from models.alert import Alerta
from models.user import User
from core.phone import normalize_phone

logger = logging.getLogger("vishguard.alerts")

NIVELES_A_GUARDAR = {"PELIGROSO", "FRAUDE", "MEDIO"}


def guardar_alerta_si_aplica(
    evaluacion: dict, usuario_id: int | None = None, *, numero_destino: str | None = None
) -> bool:
    """Guarda una alerta aplicable cuando se conoce su usuario propietario.

    Twilio proporciona el teléfono receptor, que se resuelve a una cuenta activa.
    """
    if evaluacion.get("nivel_riesgo") not in NIVELES_A_GUARDAR:
        return False

    try:
        score = float(evaluacion.get("score") or 0)
        if 0 <= score <= 1:
            score *= 100
        score = max(0, min(100, round(score)))
    except (TypeError, ValueError):
        score = 0

    mensaje = evaluacion.get("frase_critica") or evaluacion.get("texto") or "Alerta detectada"

    try:
        with Session(engine) as session:
            if usuario_id is None:
                if not numero_destino:
                    logger.warning("No se guardó la alerta: falta el teléfono receptor")
                    return False
                try:
                    phone = normalize_phone(numero_destino)
                except ValueError:
                    logger.warning("No se guardó la alerta: teléfono receptor inválido")
                    return False
                user = session.exec(select(User).where(User.phone_number == phone)).first()
            else:
                user = session.get(User, usuario_id)
            if user is None or not user.is_active:
                logger.warning("No se guardó la alerta: no hay una cuenta activa asociada")
                return False
            alerta = Alerta(
                usuario_id=user.id,
                nivel_riesgo=str(evaluacion.get("nivel_riesgo")),
                score=score,
                mensaje_alerta=str(mensaje),
                recomendacion=evaluacion.get("recomendacion"),
            )
            session.add(alerta)
            session.commit()
        return True
    except Exception:
        logger.exception("No se pudo guardar la alerta")
        return False
