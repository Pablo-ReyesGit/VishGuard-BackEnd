from fastapi import APIRouter
from database import SessionLocal, AlertHistory

router = APIRouter()

@router.get("/alerts")
def get_alert_history():
    """Endpoint HTTP para consultar el historial."""
    db = SessionLocal()
    try:
        alertas = db.query(AlertHistory).order_by(AlertHistory.timestamp.desc()).all()
        return alertas
    finally:
        db.close()