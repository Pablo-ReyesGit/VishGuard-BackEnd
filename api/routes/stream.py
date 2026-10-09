from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from core.connection_manager import ConnectionManager
from database import SessionLocal, AlertHistory
from modules.analyzer import VishingAnalyzer

router = APIRouter()
manager = ConnectionManager()
analyzer = VishingAnalyzer()

def guardar_alerta_si_aplica(evaluacion: dict):
    if evaluacion.get("nivel_riesgo") in ["PELIGROSO", "FRAUDE", "MEDIO"]:
        db = SessionLocal()
        try:
            db.add(AlertHistory(
                nivel_riesgo=evaluacion.get("nivel_riesgo"),
                score=evaluacion.get("score"),
                patrones_detectados=", ".join(evaluacion.get("patrones_detectados", [])),
                frase_critica=evaluacion.get("frase_critica", ""),
                recomendacion=evaluacion.get("recomendacion", "")
            ))
            db.commit()
        finally:
            db.close()

@router.websocket("/ws/stream")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            mensaje = await websocket.receive_text()
            if not mensaje.strip():
                continue
            evaluacion = analyzer.analizar_texto(mensaje)
            guardar_alerta_si_aplica(evaluacion)
            await websocket.send_json(evaluacion)
    except WebSocketDisconnect:
        manager.disconnect(websocket)