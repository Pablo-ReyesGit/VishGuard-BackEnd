import asyncio
import io
import logging
import os
import wave
from typing import Optional

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from core.connection_manager import manager  # SINGLETON compartido (no crear otro)
from core.ws_auth import usuario_id_desde_token
from services.stt_service import stt_service
from services.vishing_analyzer import VishingAnalyzer

logger = logging.getLogger("vishguard.stream")

router = APIRouter()

# Con WS_AUTH_REQUIRED=true la app Android debe conectar con ?token=<JWT>.
# Por defecto está apagado para no romper la app actual mientras se actualiza.
WS_AUTH_REQUIRED = os.getenv("WS_AUTH_REQUIRED", "false").lower() in ("1", "true", "yes")


def pcm_a_wav_bytes(
    pcm_data: bytes, sample_rate=16000, channels=1, sample_width=2
) -> bytes:
    """Empaqueta los bytes PCM recibidos de Android en un contenedor de audio WAV válido."""
    wav_buffer = io.BytesIO()
    with wave.open(wav_buffer, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_data)
    return wav_buffer.getvalue()


@router.websocket("/ws/stream")
async def websocket_endpoint(
    websocket: WebSocket,
    numero: str,
    token: Optional[str] = Query(default=None),
):
    if WS_AUTH_REQUIRED:
        usuario_id = await asyncio.to_thread(usuario_id_desde_token, token)
        if usuario_id is None:
            await websocket.close(code=1008)  # policy violation
            return

    if not manager.normalizar(numero):
        await websocket.close(code=1008)
        return

    clave = await manager.connect(websocket, numero)
    try:
        while True:
            mensaje = await websocket.receive_text()
            if mensaje == "ping":  # keepalive opcional desde la app
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Error en /ws/stream")
    finally:
        # Solo elimina si sigue siendo ESTE socket el registrado
        manager.disconnect(clave, websocket)


@router.websocket("/ws/stream-audio")
async def stream_audio_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("📱 Android conectado al WebSocket de audio.")

    # Instanciar el analizador al momento de aceptar la llamada
    analyzer = VishingAnalyzer()
    transcripcion_acumulada = ""

    try:
        while True:
            # Recibe el chunk de bytes PCM desde Android
            audio_bytes_pcm = await websocket.receive_bytes()

            # Convierte el buffer PCM a formato WAV para STT
            audio_bytes_wav = pcm_a_wav_bytes(audio_bytes_pcm)

            # 1. Transcribe usando los bytes WAV
            chunk_texto = stt_service.transcribir_audio_bytes(audio_bytes_wav)

            if chunk_texto and chunk_texto.strip():
                # 2. Acumula el texto a la historia de la llamada
                transcripcion_acumulada += f" {chunk_texto.strip()}"
                print(f'🎙️ Texto detectado: "{chunk_texto}" | Acumulado ({len(transcripcion_acumulada)} chars)')

                # 3. La IA analiza con Gemini y evalúa el riesgo
                analisis_resultado = analyzer.analizar_texto(transcripcion_acumulada)

                # 4. Enviar payload estructurado
                payload_respuesta = {
                    "texto_detectado": chunk_texto.strip(),
                    "transcripcion_completa": transcripcion_acumulada.strip(),
                    "analisis": analisis_resultado,
                }

                await websocket.send_json(payload_respuesta)

    except WebSocketDisconnect:
        print("📱 Llamada finalizada: Cliente Android desconectado.")
    except Exception as e:
        print(f"❌ Error en stream: {e}")
        await websocket.close()