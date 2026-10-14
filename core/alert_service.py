import logging

from database import AlertHistory, SessionLocal

logger = logging.getLogger("vishguard.alerts")

NIVELES_A_GUARDAR = {"PELIGROSO", "FRAUDE", "MEDIO"}


def guardar_alerta_si_aplica(evaluacion: dict) -> bool:
    """Guarda la alerta en la DB si el nivel de riesgo lo amerita.

    Función SÍNCRONA (SQLAlchemy). Desde código async llamarla con
    `await asyncio.to_thread(guardar_alerta_si_aplica, evaluacion)`.
    """
    if evaluacion.get("nivel_riesgo") not in NIVELES_A_GUARDAR:
        return False

    patrones = evaluacion.get("patrones_detectados") or []
    db = SessionLocal()
    try:
        db.add(
            AlertHistory(
                nivel_riesgo=evaluacion.get("nivel_riesgo"),
                score=evaluacion.get("score") or 0,
                patrones_detectados=", ".join(str(p) for p in patrones),
                frase_critica=evaluacion.get("frase_critica", ""),
                recomendacion=evaluacion.get("recomendacion", ""),
            )
        )
        db.commit()
        return True
    except Exception:
        db.rollback()
        logger.exception("No se pudo guardar la alerta")
        return False
    finally:
        db.close()

