"""T9 - AudioFrameGuard: validación de formato, tamaño, inactividad y VAD (mu-law 8 kHz de Twilio)."""
import base64
import binascii
import math
import time
from dataclasses import dataclass

def _build_mulaw_table() -> list[int]:
    table = []
    for b in range(256):
        b = ~b & 0xFF
        sign, exp, man = b & 0x80, (b >> 4) & 0x07, b & 0x0F
        sample = ((man << 3) + 0x84) << exp
        table.append((0x84 - sample) if sign else (sample - 0x84))
    return table

_MULAW = _build_mulaw_table()

@dataclass
class FrameVerdict:
    accept: bool
    speech: bool = False
    reason: str = ""
    payload: bytes = b""

class AudioFrameGuard:
    def __init__(self, sample_rate: int = 8000, max_frame_bytes: int = 4096,
                 idle_timeout: float = 15.0, vad_rms_threshold: float = 500.0):
        self.sample_rate, self.max_frame_bytes = sample_rate, max_frame_bytes
        self.idle_timeout, self.vad_rms = idle_timeout, vad_rms_threshold
        self._last = time.monotonic()

    def validate_stream_format(self, media_format: dict) -> FrameVerdict:
        """Evento 'start' de Twilio: mediaFormat {encoding, sampleRate, channels}."""
        try:
            ok = (media_format.get("encoding") == "audio/x-mulaw"
                  and int(media_format.get("sampleRate", 0)) == self.sample_rate
                  and int(media_format.get("channels", 1)) == 1)
        except (AttributeError, TypeError, ValueError):
            ok = False  # start malformado: se rechaza, nunca se propaga la excepción
        return FrameVerdict(ok, reason="" if ok else "formato no soportado")

    def inspect(self, payload_b64: str) -> FrameVerdict:
        if len(payload_b64) > self.max_frame_bytes * 2:  # chequeo barato antes de decodificar
            return FrameVerdict(False, reason="trama sobredimensionada")
        try:
            raw = base64.b64decode(payload_b64, validate=True)
        except (binascii.Error, ValueError):
            return FrameVerdict(False, reason="base64 inválido")
        if not raw or len(raw) > self.max_frame_bytes:
            return FrameVerdict(False, reason="tamaño de trama inválido")
        self._last = time.monotonic()
        return FrameVerdict(True, speech=self.is_speech(raw), payload=raw)

    def is_speech(self, mulaw: bytes) -> bool:
        """VAD por energía (RMS). Sustituible por webrtcvad si hace falta más precisión."""
        s = sum(_MULAW[b] ** 2 for b in mulaw)
        return math.sqrt(s / len(mulaw)) >= self.vad_rms

    def is_idle(self) -> bool:
        return time.monotonic() - self._last > self.idle_timeout
