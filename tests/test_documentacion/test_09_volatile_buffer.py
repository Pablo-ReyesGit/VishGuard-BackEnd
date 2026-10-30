"""Sección 9: Buffer de audio volátil.
Cubre: Ciclo de vida (ALLOCATED -> PROCESSING -> destruido), desbordamiento (BufferLimitExceeded), acceso cerrado (BufferClosed) y zeroization RAM.
"""
import pytest
from modules.Security.volatile_buffer import VolatileAudioBuffer, BufferClosed, BufferLimitExceeded

def test_buf_01_flujo_normal_take_y_peek():
    buf = VolatileAudioBuffer(max_seconds=1, bytes_per_second=100)
    buf.append(b"abcdefgh")
    assert buf.take(3) == b"abc"
    assert bytes(buf.peek()) == b"defgh"
    buf.close()
    assert len(buf) == 0

def test_buf_02_supera_capacidad_y_no_corrompe():
    buf = VolatileAudioBuffer(max_seconds=1, bytes_per_second=100)
    buf.append(b"a" * 60)
    with pytest.raises(BufferLimitExceeded):
        buf.append(b"b" * 50)
    assert len(buf) == 60 and bytes(buf.peek()) == b"a" * 60

def test_buf_03_buffer_cerrado_rechaza_operaciones():
    buf = VolatileAudioBuffer(max_seconds=1, bytes_per_second=100)
    buf.append(b"secreto")
    buf.close()
    with pytest.raises(BufferClosed):
        buf.append(b"x")
    with pytest.raises(BufferClosed):
        buf.take(1)

def test_buf_04_zeroization_al_cerrar():
    buf = VolatileAudioBuffer(max_seconds=1, bytes_per_second=100)
    buf.append(b"secreto")
    vista = buf.peek()
    buf.close()
    assert bytes(vista) == b"\x00" * 7
