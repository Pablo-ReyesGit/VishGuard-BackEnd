from fastapi import APIRouter
from sqlmodel import col, select

from api.deps import CurrentUser, SessionDep
from models.alert import Alerta

router = APIRouter()


@router.get("/alerts", response_model=list[Alerta])
def get_alert_history(session: SessionDep, current_user: CurrentUser) -> list[Alerta]:
    """Devuelve las alertas del usuario autenticado, de la más reciente a la más antigua."""
    statement = (
        select(Alerta)
        .where(Alerta.usuario_id == current_user.id)
        .order_by(col(Alerta.fecha_alerta).desc())
    )
    return list(session.exec(statement).all())
