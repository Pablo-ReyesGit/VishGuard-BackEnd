import asyncio
import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.routes.analysis import analyzer
from api.routes.twilio_stream import _texto_para_alerta
from core.connection_manager import manager

router = APIRouter()


class DebugAnalizarRequest(BaseModel):
    texto: str
    hablante: str = "llamante"


@router.post("/debug/analizar")
async def debug_analizar(data: DebugAnalizarRequest) -> dict:
    if os.getenv("VISHGUARD_DEBUG", "").lower() not in ("1", "true", "yes"):
        raise HTTPException(status_code=404)

    texto = data.texto
    hablante = data.hablante

    resultado = await asyncio.to_thread(analyzer.analizar_texto, texto)
    resultado = {**resultado, "hablante": hablante, "texto": _texto_para_alerta(texto)}
    await manager.enviar_a(manager.normalizar(os.getenv("VISHGUARD_DESTINO")), resultado)
    return resultado
