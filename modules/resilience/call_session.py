"""T3 + T9 - Políticas de ingesta de UNA llamada de Twilio (buffers volátiles, guard, VAD, límites).

La ruta /ws/twilio crea una SesionLlamada por conexión y le delega:
  * validación del formato del stream (mu-law 8 kHz mono)
  * validación y descarte de tramas (base64, tamaño) con AudioFrameGuard (uno por pista)
  * buffers volátiles por pista (VolatileAudioBuffer) con borrado al cerrar
  * límites contra abuso: ritmo de tramas, duración por pista, tramas inválidas, análisis pendientes
"""
from modules.Security.rate_limit import SlidingWindowLimiter
from modules.Security.volatile_buffer import BufferLimitExceeded, VolatileAudioBuffer
from modules.resilience.audio_frame_guard import AudioFrameGuard, FrameVerdict


class LimiteExcedido(Exception):
    def __init__(self, motivo: str):
        super().__init__(motivo)
        self.motivo = motivo


class SesionLlamada:
    MAX_INVALIDOS = 50

    def __init__(self, pistas, chunk_bytes: int, bytes_por_segundo: int = 16000, vad_rms: float = 150.0,
                 max_frame_bytes: int = 4096, max_segundos_por_pista: int = 7200, max_pendientes: int = 5,
                 frames_por_ventana: int = 1500, ventana_seg: float = 5.0, sample_rate: int = 8000,
                 min_tramas_voz: int = 10):
        self.max_segundos, self.max_pendientes = max_segundos_por_pista, max_pendientes
        self._sr = sample_rate
        self._guard = {p: AudioFrameGuard(sample_rate, max_frame_bytes, vad_rms_threshold=vad_rms) for p in pistas}
        # 1 s de margen sobre el bloque: el bloque se extrae apenas se completa
        self._buf = {p: VolatileAudioBuffer(chunk_bytes / bytes_por_segundo + 1, bytes_por_segundo) for p in pistas}
        self._chunk = chunk_bytes
        self._bps = bytes_por_segundo
        self.min_tramas_voz = min_tramas_voz   # 10 tramas de 20 ms = 0.2 s de voz
        self._voz = {p: 0 for p in pistas}
        self._mulaw = {p: 0 for p in pistas}
        self._pend = {p: 0 for p in pistas}
        self._ritmo = SlidingWindowLimiter(frames_por_ventana, ventana_seg)
        self._invalidos = 0

    # --- formato -----------------------------------------------------------------
    def formato_valido(self, media_format) -> bool:
        return next(iter(self._guard.values())).validate_stream_format(media_format).accept

    # --- tramas -------------------------------------------------------------------
    def ingresar(self, pista: str, payload_b64):
        """Devuelve (mulaw_bytes, hay_voz) o None si la trama se descarta. Lanza LimiteExcedido ante abuso."""
        if not self._ritmo.allow("frames"):
            raise LimiteExcedido("ritmo de tramas excesivo")
        if isinstance(payload_b64, str):
            veredicto = self._guard[pista].inspect(payload_b64)
        else:
            veredicto = FrameVerdict(False, reason="payload no es texto")
        if not veredicto.accept:
            self._invalidos += 1
            if self._invalidos > self.MAX_INVALIDOS:
                raise LimiteExcedido("demasiadas tramas inválidas")
            return None
        self._mulaw[pista] += len(veredicto.payload)
        if self._mulaw[pista] / self._sr > self.max_segundos:
            raise LimiteExcedido("duración máxima por pista excedida")
        return veredicto.payload, veredicto.speech

    # --- buffers -------------------------------------------------------------------
    def agregar(self, pista: str, pcm16: bytes, hay_voz: bool) -> None:
        try:
            self._buf[pista].append(pcm16)
        except BufferLimitExceeded:
            raise LimiteExcedido("buffer de sesión lleno") from None
        if hay_voz:
            self._voz[pista] += 1

    def vacio(self, pista: str) -> bool:
        return len(self._buf[pista]) == 0

    def tamano(self, pista: str) -> int:
        return len(self._buf[pista])

    def bloque_listo(self, pista: str) -> bool:
        return len(self._buf[pista]) >= self._chunk

    def extraer(self, pista: str):
        """Saca TODO lo acumulado de la pista -> (pcm, hubo_voz). El buffer queda vacío y a cero."""
        n = len(self._buf[pista])
        pcm = self._buf[pista].take(n) if n else b""
        # Voz sostenida: antes bastaba UNA trama sobre el umbral, así que el ruido de línea
        # hacía pasar casi todos los bloques por Whisper. Ahora hacen falta ~0.2 s de voz
        # (o el 20 % del bloque si es un remanente corto).
        tramas = n / (self._bps * 0.02) if self._bps else 0
        necesarias = max(1, min(self.min_tramas_voz, int(tramas * 0.2)))
        con_voz, self._voz[pista] = self._voz[pista] >= necesarias, 0
        return pcm, con_voz

    # --- análisis pendientes (contrapresión) ------------------------------------------
    def reservar(self, pista: str) -> bool:
        if self._pend[pista] >= self.max_pendientes:
            return False
        self._pend[pista] += 1
        return True

    def liberar(self, pista: str) -> None:
        self._pend[pista] = max(0, self._pend[pista] - 1)

    def cerrar(self) -> None:
        for b in self._buf.values():
            b.close()