import os
from faster_whisper import WhisperModel

class SpeechToText:
    def __init__(self, model_size: str = "tiny", device: str = "cpu", compute_type: str = "int8"):
        """
        Inicializa el modelo de transcripción de voz.
        Por defecto usa 'tiny' e 'int8' para bajo consumo en la laptop del desarrollador.
        """
        print(f"🔄 Cargando modelo Whisper ({model_size}) en {device}...")
        self.model = WhisperModel(
            model_size_or_path=model_size,
            device=device,
            compute_type=compute_type
        )
        print("✅ Modelo Whisper cargado y listo.")

    def transcribir_audio(self, ruta_archivo_audio: str) -> str:
        """
        Recibe la ruta de un archivo de audio (wav, mp3, ogg) y retorna el texto transcrito.
        """
        if not os.path.exists(ruta_archivo_audio):
            raise FileNotFoundError(f"El archivo {ruta_archivo_audio} no existe.")

        # Procesar audio indicando idioma español para acelerar
        segments, info = self.model.transcribe(
            ruta_archivo_audio,
            language="es",
            beam_size=1
        )

        texto_transcrito = ""
        for segment in segments:
            texto_transcrito += segment.text + " "

        return texto_transcrito.strip()