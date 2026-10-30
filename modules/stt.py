"""Servicios de transcripción de voz (STT) de VishGuard.

Este módulo reúne los DOS motores que vivían en ramas distintas:

  * SpeechToText         Whisper local con faster-whisper   (rama Pablo).
  * SpeechToTextService  Gemini multimodal con fallback     (rama Karen).

Los imports pesados (faster_whisper, numpy, google.genai) son PEREZOSOS: importar
este módulo no los exige; solo se cargan al crear el motor correspondiente.

La canalización de llamadas (api/routes/twilio_stream.py) elige el motor con
VISHGUARD_STT = simulado | whisper | gemini | groq.

Variables de entorno de Whisper local (todas opcionales):
  WHISPER_MODEL     tiny | base | small (defecto) | medium | large-v3 | ...
  WHISPER_DEVICE    cpu (defecto) | cuda
  WHISPER_COMPUTE   int8 (defecto en cpu) | float16 (recomendado en cuda)
  WHISPER_THREADS   hilos de CPU de CTranslate2 (0 = automático)
  WHISPER_BEAM      beam_size (defecto 5; 1 = más rápido pero mucho peor en teléfono)
  WHISPER_PROMPT    texto de contexto para el decodificador; vacío = sin prompt
  WHISPER_VAD_THRESHOLD  umbral del VAD de Silero (defecto 0.35; más bajo = deja pasar más ruido, más alto recorta palabras)
  WHISPER_LOCAL_ONLY  1 = no consulta Hugging Face al cargar el modelo (ya descargado)
  WHISPER_FALLBACK  1 = reintenta con temperatura si la decodificación sale mal (más preciso pero
                    puede triplicar el tiempo de un bloque ruidoso; defecto 0 para tiempo real)

CAMBIOS RESPECTO A LA VERSIÓN ANTERIOR (audio telefónico de 8 kHz):
  - Modelo por defecto `small` (con `tiny` el español telefónico sale casi ininteligible).
  - beam_size=5; fallback de temperatura opcional (WHISPER_FALLBACK=1). Los bucles de
    repetición ("y todo el grasa y todo el grasa...") se colapsan en el postprocesado.
  - condition_on_previous_text=False, without_timestamps=True (más rápido en bloques cortos).
  - VAD de Silero menos agresivo (no recorta palabras sueltas del teléfono).
  - initial_prompt con vocabulario del dominio (tarjeta, crédito, CVV, clave...).
  - Filtros posteriores: segmentos sin voz, alucinaciones típicas, eco del prompt y
    colapso de repeticiones (sin tocar dígitos dictados).
  - Remuestreo 8 -> 16 kHz con filtro FIR (numpy) en vez de interpolación lineal.
  - Precalentamiento del modelo al cargarlo y log de tiempos por bloque.
"""

import io
import logging
import os
import re
import threading
import time
import unicodedata
import warnings
import wave

from dotenv import load_dotenv

# Silencia la advertencia de Automatic Function Calling (AFC) de Gemini
warnings.filterwarnings("ignore", category=UserWarning, module="google.genai")

load_dotenv()

logger = logging.getLogger("vishguard.stt")


# ==============================================================================
# UTILIDADES DE AUDIO
# ==============================================================================
def pcm_a_wav_bytes(
    pcm_data: bytes, sample_rate: int = 16000, channels: int = 1, sample_width: int = 2
) -> bytes:
    """Convierte bytes PCM a un contenedor WAV en memoria."""
    wav_buffer = io.BytesIO()
    with wave.open(wav_buffer, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_data)
    return wav_buffer.getvalue()


_FIR_2X = None


def _fir_2x():
    """Filtro paso bajo (63 taps, corte 4 kHz a 16 kHz) para el remuestreo x2."""
    global _FIR_2X
    if _FIR_2X is None:
        import numpy as np

        n = 63
        t = np.arange(n) - (n - 1) / 2
        h = np.sinc(0.5 * t) * np.hanning(n)  # corte = 0.25 ciclos/muestra = 4 kHz
        h *= 2.0 / h.sum()  # ganancia 2: compensa los ceros insertados
        _FIR_2X = h.astype(np.float32)
    return _FIR_2X


def pcm8k_a_16k(pcm8k: bytes) -> bytes:
    """PCM16 mono 8 kHz (telefonía) -> PCM16 mono 16 kHz.

    16 kHz es la frecuencia que esperan Whisper y Gemini: si se les entrega audio
    de 8 kHz etiquetado como 16 kHz, suena al doble de velocidad y transcriben mal.
    Se inserta un cero entre muestras y se filtra con un FIR paso bajo, lo que
    evita las imágenes espectrales de la interpolación lineal.
    """
    pcm8k = pcm8k[: len(pcm8k) // 2 * 2]
    if not pcm8k:
        return b""
    try:
        import numpy as np

        x = np.frombuffer(pcm8k, dtype=np.int16).astype(np.float32)
        up = np.zeros(x.size * 2, dtype=np.float32)
        up[::2] = x
        y = np.convolve(up, _fir_2x(), mode="same")
        return np.clip(y, -32768, 32767).astype(np.int16).tobytes()
    except Exception:  # respaldo: la versión original con audioop
        import audioop  # stdlib hasta Python 3.12; en 3.13+ lo aporta audioop-lts

        pcm16k, _ = audioop.ratecv(pcm8k, 2, 1, 8000, 16000, None)
        return pcm16k


# ==============================================================================
# POSTPROCESADO DEL TEXTO DE WHISPER
# ==============================================================================
_PALABRAS_DIGITO = frozenset(
    {"cero", "uno", "una", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve"}
)

# Frases que Whisper inventa cuando oye ruido o silencio (ya normalizadas: sin tildes).
_MARCAS_ALUCINACION = (
    "amara.org",
    "subtitulos realizados por",
    "gracias por ver",
    "suscribete",
)

# Una frase de 1 a 6 palabras (solo letras) repetida 3 o más veces seguidas.
_RE_REPETICION = re.compile(r"(?i)\b((?:[^\W\d_]+\s+){0,5}[^\W\d_]+)(?:\s+\1\b){2,}")


def _norm(texto: str) -> str:
    """Minúsculas y sin tildes, para comparar."""
    nfd = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def _solo_palabras(texto: str) -> str:
    return " ".join(re.sub(r"[^\w\s.]", " ", _norm(texto)).split())


def _colapsar_repeticiones(texto: str) -> str:
    """'y todo el grasa y todo el grasa y todo el grasa' -> 'y todo el grasa'.

    No colapsa secuencias de dígitos dictados ("siete siete siete") ni números.
    """
    plano = re.sub(r"\s+", " ", re.sub(r"[,.;:¡!¿?]+", " ", texto)).strip()

    def _rep(m: re.Match) -> str:
        grupo = m.group(1)
        if all(p.lower() in _PALABRAS_DIGITO for p in grupo.split()):
            return m.group(0)
        return grupo

    colapsado = _RE_REPETICION.sub(_rep, plano)
    return colapsado if colapsado != plano else texto


# ==============================================================================
# MOTOR 1: WHISPER LOCAL (faster-whisper) - rama Pablo
# ==============================================================================
_PROMPT_DEFECTO = (
    "Conversación telefónica en español. Se habla de banco, tarjeta de crédito, "
    "número de tarjeta, código de seguridad, clave y contraseña."
)

# Silero VAD: relleno amplio para no comerse palabras sueltas del teléfono. El umbral se
# lee de WHISPER_VAD_THRESHOLD: demasiado bajo deja pasar ruido de línea y Whisper gasta
# segundos decodificando "voz" que no existe.


class SpeechToText:
    def __init__(
        self,
        model_size: str | None = None,
        device: str | None = None,
        compute_type: str | None = None,
    ):
        """Inicializa el modelo de transcripción de voz (ver variables WHISPER_* arriba)."""
        from faster_whisper import WhisperModel

        model_size = model_size or os.getenv("WHISPER_MODEL", "base")
        device = device or os.getenv("WHISPER_DEVICE", "cpu")
        compute_type = compute_type or os.getenv(
            "WHISPER_COMPUTE", "float16" if device == "cuda" else "int8"
        )
        cpu_threads = int(os.getenv("WHISPER_THREADS", "0"))
        self.beam_size = max(1, int(os.getenv("WHISPER_BEAM", "1")))
        prompt = os.getenv("WHISPER_PROMPT", _PROMPT_DEFECTO).strip()
        self.prompt = prompt or None
        self._vad = dict(
            threshold=float(os.getenv("WHISPER_VAD_THRESHOLD", "0.35")),
            min_silence_duration_ms=500,
            speech_pad_ms=400,
        )
        # Sin fallback: una sola pasada por bloque (costo predecible). Con WHISPER_FALLBACK=1
        # un bloque ruidoso se re-decodifica hasta 3 veces.
        self._temperaturas = (
            [0.0, 0.2, 0.4] if os.getenv("WHISPER_FALLBACK", "0") == "1" else [0.0]
        )
        self._prompt_norm = _solo_palabras(prompt) if prompt else ""

        logger.info(
            "Cargando Whisper (%s, %s, %s, beam=%s)...", model_size, device, compute_type, self.beam_size
        )
        self.model = WhisperModel(
            model_size_or_path=model_size,
            device=device,
            compute_type=compute_type,
            cpu_threads=cpu_threads,
            # Con WHISPER_LOCAL_ONLY=1 no consulta Hugging Face al cargar (usa la caché local).
            local_files_only=os.getenv("WHISPER_LOCAL_ONLY", "0") == "1",
        )
        # Dos hablantes se transcriben en hilos distintos: un solo modelo, un cerrojo.
        self._cerrojo = threading.Lock()
        self._calentar()
        logger.info("Whisper cargado y calentado.")

    # ------------------------------------------------------------------
    def _calentar(self) -> None:
        """Una pasada con ruido para que la primera llamada real no pague la inicialización."""
        try:
            import numpy as np

            ruido = (np.random.randn(16000) * 0.01).astype(np.float32)
            segmentos, _ = self.model.transcribe(
                ruido, language="es", beam_size=1, without_timestamps=True
            )
            list(segmentos)
        except Exception:
            logger.warning("No se pudo calentar Whisper (no es grave)", exc_info=True)

    def _limpiar(self, texto: str) -> str:
        texto = (texto or "").strip()
        if not texto:
            return ""
        plano = _solo_palabras(texto)
        if any(marca in plano for marca in _MARCAS_ALUCINACION):
            return ""
        # Eco del prompt: con ruido, Whisper a veces devuelve el propio initial_prompt.
        if self._prompt_norm and len(plano.split()) >= 4 and plano in self._prompt_norm:
            return ""
        return _colapsar_repeticiones(texto)

    def _transcribir_array(self, audio) -> str:
        """Transcribe un arreglo float32 mono a 16 kHz en [-1, 1]."""
        with self._cerrojo:
            segmentos, _info = self.model.transcribe(
                audio,
                language="es",
                task="transcribe",
                beam_size=self.beam_size,
                temperature=self._temperaturas,
                compression_ratio_threshold=2.0,    # detecta bucles de repetición
                log_prob_threshold=-1.0,
                no_speech_threshold=0.5,
                condition_on_previous_text=False,
                initial_prompt=self.prompt,
                without_timestamps=True,
                vad_filter=True,
                vad_parameters=self._vad,
            )
            partes = []
            # `segmentos` es un generador: se consume DENTRO del cerrojo.
            for seg in segmentos:
                if seg.no_speech_prob > 0.6 and seg.avg_logprob < -1.0:
                    continue  # segmento casi seguro sin voz real
                texto = seg.text.strip()
                if texto:
                    partes.append(texto)
        return self._limpiar(" ".join(partes))

    # ------------------------------------------------------------------
    def transcribir_audio(self, ruta_archivo_audio: str) -> str:
        """Recibe la ruta de un archivo de audio (wav, mp3, ogg) y retorna el texto."""
        if not os.path.exists(ruta_archivo_audio):
            raise FileNotFoundError(f"El archivo {ruta_archivo_audio} no existe.")
        from faster_whisper.audio import decode_audio

        audio = decode_audio(ruta_archivo_audio, sampling_rate=16000)
        return self._transcribir_array(audio)

    def transcribir_pcm(self, pcm8k: bytes) -> str:
        """Transcribe un bloque de audio EN MEMORIA (PCM16 mono 8 kHz, de una llamada).

        Es lo que usa la canalización de llamadas en tiempo real: no pasa por disco.
        """
        import numpy as np

        t0 = time.perf_counter()
        pcm16k = pcm8k_a_16k(pcm8k)
        audio = np.frombuffer(pcm16k, dtype=np.int16).astype(np.float32) / 32768.0
        texto = self._transcribir_array(audio)

        duracion = len(pcm8k) / 16000  # 8 kHz x 2 bytes
        usado = time.perf_counter() - t0
        logger.info(
            "[STT] %.1f s de audio -> %.2f s de proceso (x%.2f del tiempo real, incluye espera del cerrojo)",
            duracion,
            usado,
            usado / duracion if duracion else 0.0,
        )
        return texto


# ==============================================================================
# MOTOR 2: GEMINI MULTIMODAL - rama Karen (sin cambios)
# ==============================================================================
class SpeechToTextService:
    def __init__(self):
        load_dotenv()
        self.api_key = os.getenv("GEMINI_API_KEY")

        if self.api_key:
            from google import genai

            self.client = genai.Client(api_key=self.api_key)
        else:
            self.client = None
            print("⚠️ Sin GEMINI_API_KEY en STT Service.")

        # Modelos asignados con fallback
        self.modelos = [
            "gemini-3.5-flash-lite",
            "gemini-3.5-flash",
            "gemini-3.8-flash",
        ]

    def transcribir_audio_bytes(self, pcm_bytes: bytes, sample_rate: int = 16000) -> str:
        """Transcribe PCM16 mono. `sample_rate` debe ser el REAL del audio (por defecto 16 kHz)."""
        if not self.client:
            return ""

        try:
            from google.genai import types

            wav_data = pcm_a_wav_bytes(pcm_bytes, sample_rate=sample_rate)

            prompt = (
                "Transcribe exactamente las palabras habladas en este fragmento de audio"
                " telefónico en español. Los números que se dicten (tarjetas, códigos,"
                " cuentas) escríbelos con cifras, dígito por dígito si se dictan por"
                " separado (ejemplo: 1 1 1 2 3 3 4). Si no hay voz clara, responde con"
                " una cadena vacía. Devuelve ÚNICAMENTE el texto transcrito, sin"
                " comentarios ni anotaciones entre paréntesis."
            )
            # temperature=0: transcripción determinista. AFC desactivado: no se usan
            # herramientas y evita el aviso "AFC is enabled" en cada llamada.
            config = types.GenerateContentConfig(
                temperature=0,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            )

            # Intento con fallback entre modelos de Gemini
            for modelo in self.modelos:
                try:
                    response = self.client.models.generate_content(
                        model=modelo,
                        contents=[
                            types.Part.from_bytes(data=wav_data, mime_type="audio/wav"),
                            prompt,
                        ],
                        config=config,
                    )
                    texto = (response.text or "").strip()
                    # "(silencio)", "[ruido]"...: anotaciones, no voz
                    if re.fullmatch(r"[\(\[].*[\)\]]", texto):
                        return ""
                    if texto:
                        return texto
                except Exception as e_model:
                    print(f"⚠️ Falló transcripción con {modelo}: {e_model}. Probando siguiente...")

            return ""
        except Exception as e:
            print(f"❌ Error en transcripción con Gemini: {e}")
            return ""