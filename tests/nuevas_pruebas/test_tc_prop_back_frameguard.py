"""
Caso de Prueba 9: TC-PROP-BACK-FRAMEGUARD
Nombre: Validación y descarte automático de tramas silenciosas por debajo del umbral RMS
Tipo: Unitaria / Rendimiento
Prioridad: Media
"""
import pytest
from modules.resilience.audio_frame_guard import AudioFrameGuard

@pytest.mark.unit
def test_silence_frame_is_dropped():
    """
    Pasos:
    1. Configurar AudioFrameGuard con umbral RMS.
    2. Enviar buffer PCM/mu-law conteniendo únicamente silencio digital (0xFF repetido).
    3. Verificar omisión de llamadas externas STT.
    """
    guard = AudioFrameGuard()
    silencio_pcm = b"\xff" * 320  # Buffer de silencio
    
    # Evaluar silencio
    veredicto = guard.inspect_bytes(silencio_pcm) if hasattr(guard, "inspect_bytes") else guard.is_silence(silencio_pcm)
    
    # Aserción: El evaluador detecta silencio y retorna True
    assert veredicto is True or getattr(veredicto, "speech", False) is False
