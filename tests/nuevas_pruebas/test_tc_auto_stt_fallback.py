"""
Caso de Prueba 5: TC-AUTO-STT-FALLBACK
Nombre: Fallback en cascada automático del servicio Gemini STT ante fallos del modelo primario
Tipo: Unitaria / Resiliencia
Prioridad: Alta
"""
import pytest
from unittest.mock import AsyncMock

@pytest.mark.unit
@pytest.mark.asyncio
async def test_gemini_service_falls_back_to_the_next_model(mocker):
    """
    Pasos:
    1. Configurar Fake cliente Gemini para elevar excepción en gemini-3.5-flash-lite.
    2. Invocar transcribir_audio_bytes().
    3. Verificar que conmuta automáticamente a gemini-3.5-flash.
    """
    modelos_llamados = []
    
    async def mock_gemini_call(modelo, audio_bytes):
        modelos_llamados.append(modelo)
        if modelo == "gemini-3.5-flash-lite":
            raise RuntimeError("API Rate Limit 429 en modelo primario")
        return {"text": "Transcripción exitosa con modelo secundario"}

    mocker.patch("services.stt_gemini.call_model", side_effect=mock_gemini_call)
    
    from services.stt_gemini import transcribir_con_fallback
    
    resultado = await transcribir_con_fallback(b"AUDIO_WAV_BYTES_3KB")
    
    # Aserción: Historial de modelos invocados en cascada
    assert modelos_llamados == ["gemini-3.5-flash-lite", "gemini-3.5-flash"]
    assert resultado["text"] == "Transcripción exitosa con modelo secundario"
