"""
volatile_buffer.py
-------------------
Implementación de la máquina de estados "Volatile Audio Buffer (RAM)" (Sheet2).

Estados:
  [*] -> Unallocated : Recibe ráfaga de bytes (WebSocket)
  Unallocated -> Allocated       : __init__(raw_bytes)
  Allocated   -> Processing      : get_data()
  Processing  -> Zeroing         : destroy() / __exit__()
  Zeroing     -> GarbageCollected: __del__() / Limpieza de Puntero
  GarbageCollected -> [*]
"""

from enum import Enum, auto


class BufferState(Enum):
    UNALLOCATED = auto()
    ALLOCATED = auto()
    PROCESSING = auto()
    ZEROING = auto()
    GARBAGE_COLLECTED = auto()


class VolatileAudioBuffer:
    """
    Buffer de audio volátil en RAM. Se comporta como context manager
    para garantizar que la memoria se sobrescriba (Zeroing) al salir
    del bloque `with`, y ademas expone __del__ como red de seguridad.
    """

    def __init__(self, raw_bytes: bytes):
        # Unallocated --> Allocated : __init__(raw_bytes)
        self._state = BufferState.UNALLOCATED
        self._buffer = bytearray(raw_bytes)  # bytearray reservado en RAM
        self._state = BufferState.ALLOCATED

    def get_data(self) -> bytes:
        # Allocated --> Processing : get_data()
        if self._state not in (BufferState.ALLOCATED, BufferState.PROCESSING):
            raise RuntimeError(f"No se puede leer el buffer en estado {self._state}")
        self._state = BufferState.PROCESSING  # Leyendo bytes para Whisper STT
        return bytes(self._buffer)

    def destroy(self):
        # Processing --> Zeroing : destroy() / __exit__()
        if self._state == BufferState.GARBAGE_COLLECTED:
            return
        for i in range(len(self._buffer)):
            self._buffer[i] = 0x00  # Sobrescribiendo memoria con bytes 0x00
        self._state = BufferState.ZEROING
        self._collect()

    def _collect(self):
        # Zeroing --> GarbageCollected : __del__() / Limpieza de Puntero
        self._buffer = None
        self._state = BufferState.GARBAGE_COLLECTED  # --> [*]

    # Soporte de context manager: with VolatileAudioBuffer(data) as buf: ...
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.destroy()
        return False

    def __del__(self):
        # Red de seguridad por si nunca se llamó a destroy()
        if getattr(self, "_state", None) not in (None, BufferState.GARBAGE_COLLECTED):
            self.destroy()


if __name__ == "__main__":
    with VolatileAudioBuffer(b"\x01\x02\x03audio-fragmento") as buf:
        data = buf.get_data()
        print("Procesando bytes:", data)
    print("Estado final:", buf._state)  # GARBAGE_COLLECTED