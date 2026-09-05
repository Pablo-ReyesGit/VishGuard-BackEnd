from fastapi import APIRouter
from pydantic import BaseModel
from modules.analyzer import VishingAnalyzer

# 👈 Esta es la variable exacta que main.py está buscando
router = APIRouter()
analyzer = VishingAnalyzer()

class CallRequest(BaseModel):
    texto: str

@router.post("/analizar-llamada")
def analizar_llamada(data: CallRequest):
    # Llama al analizador (que usará Groq si detecta la clave en .env)
    return analyzer.analizar_texto(data.texto)