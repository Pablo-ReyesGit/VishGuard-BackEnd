from fastapi import APIRouter, Request
from pydantic import BaseModel
from services.heuristic_engine import evaluar_amenaza

router = APIRouter()

class CallRequest(BaseModel):
    texto: str

@router.post("/analizar-llamada")
def analizar_llamada(data: CallRequest, request: Request):
    nivel, score, recomendacion, hallazgos = evaluar_amenaza(data.texto)
    return {"nivel_riesgo": nivel, "score": score, "recomendacion": recomendacion}