"""T3 - Buffer volátil de audio en RAM (sin persistencia, sin copias intermedias)."""

class BufferLimitExceeded(Exception):
    pass

class BufferClosed(Exception):
    pass

class VolatileAudioBuffer:
    """Buffer preasignado. Twilio: mu-law 8 kHz mono => 8000 bytes/s."""

    def __init__(self, max_seconds: float = 30.0, bytes_per_second: int = 8000):
        self._cap = int(max_seconds * bytes_per_second)
        self._bps = bytes_per_second
        self._buf = bytearray(self._cap)
        self._view = memoryview(self._buf)
        self._used = 0
        self._closed = False

    def __len__(self) -> int:
        return self._used

    @property
    def seconds(self) -> float:
        return self._used / self._bps

    def append(self, chunk) -> None:
        if self._closed:
            raise BufferClosed()
        n = len(chunk)
        if self._used + n > self._cap:
            raise BufferLimitExceeded(f"límite de sesión ({self._cap} bytes)")
        self._view[self._used:self._used + n] = chunk  # copia única, directa al destino
        self._used += n

    def peek(self) -> memoryview:
        """Vista de solo lectura sin copia (no usar tras close())."""
        return self._view[:self._used].toreadonly()

    def take(self, n: int) -> bytes:
        """Extrae y elimina los primeros n bytes (única copia: la que consume el STT)."""
        if self._closed:
            raise BufferClosed()
        n = min(n, self._used)
        out = bytes(self._view[:n])
        rem = self._used - n
        if rem:
            self._view[:rem] = self._view[n:self._used]  # compactación in-place
        self._view[rem:self._used] = bytes(self._used - rem)  # borrado de lo sobrante
        self._used = rem
        return out

    def close(self) -> None:
        """Descarta y pone a cero. Idempotente."""
        if self._closed:
            return
        self._view[:self._used] = bytes(self._used)
        self._used = 0
        self._closed = True
        self._view.release()
        self._buf = bytearray()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
