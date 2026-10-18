"""Sección 2: Conversión PCM → WAV.
Cubre: Validación de buffer PCM, extracción de tramas, formato audio/x-mulaw y purga de grabaciones WAV por TTL.
"""
import os
import pytest
import api.routes.twilio_stream as tw
from modules.resilience.call_session import SesionLlamada, LimiteExcedido

def test_pcm_01_extraer_vacia_el_buffer_y_reporta_voz():
    s = SesionLlamada(tw.HABLANTES, chunk_bytes=48000)
    s.agregar("inbound", b"\x01\x00" * 100, True)
    pcm, voz = s.extraer("inbound")
    assert len(pcm) == 200 and voz and s.vacio("inbound") and s.extraer("inbound") == (b"", False)

@pytest.mark.parametrize("fmt,ok", [
    ({"encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1}, True),
    ({"encoding": "audio/x-mulaw", "sampleRate": 16000}, False),
    ("x", False),
    (None, False)
])
def test_pcm_02_formato_mu_law_valido(fmt, ok):
    s = SesionLlamada(tw.HABLANTES, chunk_bytes=48000)
    assert s.formato_valido(fmt) is ok

def test_pcm_03_grabaciones_viejas_se_purgan_por_ttl(tmp_path, monkeypatch):
    monkeypatch.setenv("VISHGUARD_GUARDAR_WAV", "1")
    monkeypatch.setenv("VISHGUARD_WAV_DIR", str(tmp_path))
    monkeypatch.setattr(tw, "WAV_TTL_HORAS", 1)
    
    vieja = tmp_path / "vieja.wav"
    vieja.write_bytes(b"x")
    os.utime(vieja, (0, 0))
    
    reciente = tmp_path / "reciente.wav"
    reciente.write_bytes(b"x")
    
    g = tw.GrabadorWav("CA1")
    assert not vieja.exists() and reciente.exists() and g.ruta.exists()
