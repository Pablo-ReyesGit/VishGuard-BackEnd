import io
import os
import wave
import warnings
from dotenv import load_dotenv
from google import genai
from google.genai import types

# Silencia la advertencia de Automatic Function Calling (AFC) de Gemini
warnings.filterwarnings("ignore", category=UserWarning, module="google.genai")

load_dotenv()


def pcm_a_wav_bytes(
    pcm_data: bytes, sample_rate=16000, channels=1, sample_width=2
) -> bytes:
  """Convierte bytes PCM a un contenedor WAV en memoria."""
  wav_buffer = io.BytesIO()
  with wave.open(wav_buffer, "wb") as wav_file:
    wav_file.setnchannels(channels)
    wav_file.setsampwidth(sample_width)
    wav_file.setframerate(sample_rate)
    wav_file.writeframes(pcm_data)
  return wav_buffer.getvalue()


class SpeechToTextService:

  def __init__(self):
    load_dotenv()
    self.api_key = os.getenv("GEMINI_API_KEY")

    if self.api_key:
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

  def transcribir_audio_bytes(self, pcm_bytes: bytes) -> str:
    if not self.client:
      return ""

    try:
      wav_data = pcm_a_wav_bytes(pcm_bytes)

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
          print(
              f"⚠️ Falló transcripción con {modelo}: {e_model}. Probando"
              " siguiente..."
          )

      return ""
    except Exception as e:
      print(f"❌ Error en transcripción con Gemini: {e}")
      return ""