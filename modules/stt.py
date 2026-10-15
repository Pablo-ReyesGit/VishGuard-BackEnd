"""Servicios de transcripción de voz (STT) de VishGuard.

Este módulo reúne los DOS motores que vivían en ramas distintas y que el merge
había dejado en uno solo (la versión de la rama Karen sobrescribió a la de Pablo):

  * SpeechToText         Whisper local con faster-whisper   (rama Pablo).
  * SpeechToTextService  Gemini multimodal con fallback     (rama Karen).

Los imports pesados (faster_whisper, numpy, google.genai) son PEREZOSOS: importar
este módulo no los exige; solo se cargan al crear el motor correspondiente. Así
la app arranca aunque un motor que no se usa no esté instalado.

La canalización de llamadas (api/routes/twilio_stream.py) elige el motor con la
variable VISHGUARD_STT = simulado | whisper | gemini | groq.
"""

import io
import os
import threading
import warnings
import wave

from dotenv import load_dotenv

# Silencia la advertencia de Automatic Function Calling (AFC) de Gemini
warnings.filterwarnings("ignore", category=UserWarning, module="google.genai")

load_dotenv()


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


def pcm8k_a_16k(pcm8k: bytes) -> bytes:
    """PCM16 mono 8 kHz (telefonía) -> PCM16 mono 16 kHz.

    16 kHz es la frecuencia que esperan Whisper y Gemini: si se les entrega audio
    de 8 kHz etiquetado como 16 kHz, suena al doble de velocidad y transcriben mal.
    """
    import audioop  # stdlib hasta Python 3.12; en 3.13+ lo aporta audioop-lts

    pcm16k, _ = audioop.ratecv(pcm8k, 2, 1, 8000, 16000, None)
    return pcm16k


# ==============================================================================
# MOTOR 1: WHISPER LOCAL (faster-whisper) - rama Pablo
# ==============================================================================
class SpeechToText:
    def __init__(
        self,
        model_size: str | None = None,
        device: str | None = None,
        compute_type: str | None = None,
    ):
        """Inicializa el modelo de transcripción de voz.

        Por defecto usa 'tiny' e 'int8' para bajo consumo en la laptop del
        desarrollador. Se puede cambiar con WHISPER_MODEL, WHISPER_DEVICE y
        WHISPER_COMPUTE sin tocar el código.
        """
        from faster_whisper import WhisperModel

        model_size = model_size or os.getenv("WHISPER_MODEL", "tiny")
        device = device or os.getenv("WHISPER_DEVICE", "cpu")
        compute_type = compute_type or os.getenv("WHISPER_COMPUTE", "int8")

        print(f"🔄 Cargando modelo Whisper ({model_size}) en {device}...")
        self.model = WhisperModel(
            model_size_or_path=model_size,
            device=device,
            compute_type=compute_type,
        )
        print("✅ Modelo Whisper cargado y listo.")
        # Dos hablantes se transcriben en hilos distintos: un solo modelo, un cerrojo.
        self._cerrojo = threading.Lock()

    def transcribir_audio(self, ruta_archivo_audio: str) -> str:
        """Recibe la ruta de un archivo de audio (wav, mp3, ogg) y retorna el texto."""
        if not os.path.exists(ruta_archivo_audio):
            raise FileNotFoundError(f"El archivo {ruta_archivo_audio} no existe.")

        with self._cerrojo:
            # Idioma español indicado para acelerar
            segments, _info = self.model.transcribe(
                ruta_archivo_audio,
                language="es",
                beam_size=1,
            )
            return " ".join(segment.text.strip() for segment in segments).strip()

    def transcribir_pcm(self, pcm8k: bytes) -> str:
        """Transcribe un bloque de audio EN MEMORIA (PCM16 mono 8 kHz, de una llamada).

        Es lo que usa la canalización de llamadas en tiempo real: no pasa por disco.
        """
        import numpy as np

        pcm16k = pcm8k_a_16k(pcm8k)
        # faster-whisper acepta un arreglo float32 mono a 16 kHz con valores en [-1, 1]
        audio = np.frombuffer(pcm16k, dtype=np.int16).astype(np.float32) / 32768.0

        with self._cerrojo:
            # vad_filter descarta silencios y tonos sin voz: evita que Whisper
            # "alucine" texto donde no hay palabras (tono de llamada, ruido).
            segments, _info = self.model.transcribe(
                audio,
                language="es",
                beam_size=1,
                vad_filter=True,
            )
            # `segments` es un generador: se consume DENTRO del cerrojo.
            return " ".join(segment.text.strip() for segment in segments).strip()


# ==============================================================================
# MOTOR 2: GEMINI MULTIMODAL - rama Karen
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
                "Transcribe exactamente las palabras habladas en este fragmento de"
                " audio en español. Devuelve ÚNICAMENTE el texto transcrito, sin"
                " comentarios adicionales."
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
                    )
                    if response.text:
                        return response.text.strip()
                except Exception as e_model:
                    print(f"⚠️ Falló transcripción con {modelo}: {e_model}. Probando siguiente...")

            return ""
        except Exception as e:
            print(f"❌ Error en transcripción con Gemini: {e}")
            return ""