import logging
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError

from api.deps import CurrentUser, SessionDep
from core.alert_service import construir_alerta
from modules.analyzer import VishingAnalyzer

router = APIRouter()
analyzer = VishingAnalyzer()
logger = logging.getLogger("vishguard.simulations")

class CallRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    texto: str = Field(min_length=1, max_length=20000)


class SimulationResponse(BaseModel):
    nivel_riesgo: Literal["BAJO", "MEDIO", "PELIGROSO", "FRAUDE"]
    score: int = Field(ge=0, le=100)
    mensaje_alerta: str
    recomendacion: str | None = None
    es_simulacion: Literal[True] = True
    alerta_guardada: Literal[True] = True
    alerta_id: int


@router.post("/analizar-llamada", response_model=SimulationResponse)
def analizar_llamada(
    data: CallRequest, session: SessionDep, current_user: CurrentUser
) -> SimulationResponse:
    """Analiza y guarda la simulación en la cuenta del usuario autenticado."""
    evaluacion = analyzer.analizar_texto(data.texto)
    alerta = construir_alerta(evaluacion, current_user.id, es_simulacion=True)
    try:
        session.add(alerta)
        session.flush()
        result = SimulationResponse(
            nivel_riesgo=alerta.nivel_riesgo,
            score=alerta.score,
            mensaje_alerta=alerta.mensaje_alerta,
            recomendacion=alerta.recomendacion,
            alerta_id=alerta.id,
        )
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        logger.error("No se pudo guardar la simulación (%s)", type(exc).__name__)
        raise HTTPException(
            status_code=503,
            detail="No se pudo guardar la simulación. Inténtalo nuevamente.",
        ) from exc
    return result
