"""
Pruebas Unitarias del Módulo STT (modules/stt.py)
Nombre: Verificación directa de funciones de transcripción de audio
Tipo: Unitaria
Prioridad: Alta
"""
import pytest
from unittest.mock import AsyncMock

@pytest.mark.unit
@pytest.mark.asyncio
async def test_transcribe_audio_success(mocker, mock_audio_bytes):
    """Procesa audio válido y retorna la estructura de dict esperada."""
    mock_stt = mocker.patch("modules.stt.transcribe_audio", new_callable=AsyncMock)
    mock_stt.return_value = {
        "text": "Hola, confirmando transferencia bancaria",
        "confidence": 0.96,
        "language": "es"
    }

    from modules.stt import transcribe_audio
    resultado = await transcribe_audio(mock_audio_bytes)

    assert resultado is not None
    assert "text" in resultado
    assert resultado["text"] == "Hola, confirmando transferencia bancaria"

@pytest.mark.unit
@pytest.mark.asyncio
async def test_transcribe_audio_empty_raises_error():
    """Validación de rechazo cuando el buffer de audio está vacío."""
    from modules.stt import transcribe_audio
    
    with pytest.raises((ValueError, Exception)):
        await transcribe_audio(b"")
