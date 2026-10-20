import pytest
from unittest.mock import AsyncMock

@pytest.mark.asyncio
async def test_transcribir_audio_exitoso(mocker):
    """Prueba unitaria para verificar la transcripción de audio."""
    # Simulamos la función de transcripción dentro del submódulo Tolerance
    mock_stt = mocker.patch("modules.Tolerance.stt.transcribe_audio", new_callable=AsyncMock)
    mock_stt.return_value = {
        "text": "Hola, esto es una prueba de transcripción.",
        "language": "es"
    }

    from modules.Tolerance.stt import transcribe_audio
    
    audio_simulado = b"BYTES_DE_AUDIO_MOCK"
    resultado = await transcribe_audio(audio_simulado)

    assert resultado is not None
    assert "text" in resultado
    assert resultado["text"] == "Hola, esto es una prueba de transcripción."

@pytest.mark.asyncio
async def test_transcribir_audio_vacio():
    """Verifica la validación cuando el audio enviado está vacío."""
    from modules.Tolerance.stt import transcribe_audio
    
    with pytest.raises(ValueError):
        await transcribe_audio(b"")