# ==============================================================================
# MÓDULO DE INTEGRACIÓN DE STREAMING DE VOZ DE TWILIO (VishGuard)
# ==============================================================================
# Este módulo se encarga de:
# 1. Recibir la señal de una llamada telefónica entrante vía Webhook HTTP.
# 2. Responder a Twilio con instrucciones en formato XML (TwiML) para iniciar un Stream.
# 3. Abrir un canal WebSocket (`/ws/twilio`) para recibir fragmentos de audio en tiempo real.
# 4. Decodificar el audio de mu-law a PCM, acumularlo en un buffer y pasarlo por la
#    canalización de análisis (Whisper -> VishingAnalyzer -> Base de Datos).
# ==============================================================================

import base64
import json

# Importación segura de audioop (soporta Python 3.13 mediante audioop_lts si aplica)
try:
    import audioop
except ImportError:
    import audioopy as audioop

# Componentes web de FastAPI
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

# SDK de Twilio para construir respuestas TwiML (XML especial para llamadas)
from twilio.twiml.voice_response import VoiceResponse, Start, Dial

# Importaciones de la arquitectura propia de VishGuard
from database import SessionLocal, AlertHistory
from modules.analyzer import VishingAnalyzer
from core.connection_manager import manager

# Inicialización del enrutador modular de FastAPI
router = APIRouter()


# Instancia del motor de análisis de fraudes (Groq LLM o motor heurístico de respaldo)
analyzer = VishingAnalyzer()


# ==============================================================================
# PASO 1: WEBHOOK HTTP - RECEPCIÓN DE LA LLAMADA
# ==============================================================================

@router.post("/twilio/voice")
async def twilio_voice_webhook(request: Request):
    host = request.headers.get("host")
    ws_protocol = "wss" if "ngrok" in host or request.headers.get("x-forwarded-proto") == "https" else "ws"

    numero_destino = "+50257008032"  # el celular real que debe sonar

    response = VoiceResponse()

    # Inicia el streaming de audio SIN bloquear la llamada
    start = Start()
    start.stream(url=f"{ws_protocol}://{host}/ws/twilio?to={numero_destino}")
    response.append(start)

    # Reenvía la llamada real al teléfono del usuario
    dial = Dial()
    dial.number(numero_destino)
    response.append(dial)

    return HTMLResponse(content=str(response), media_type="application/xml")

# ==============================================================================
# PASO 2: WEBSOCKET - PROCESAMIENTO DE AUDIO EN TIEMPO REAL
# ==============================================================================
@router.websocket("/ws/twilio")
async def twilio_websocket_endpoint(websocket: WebSocket, to: str):
    """
    Canal de comunicación continua de doble vía.
    Twilio transmite aquí el audio de la llamada dividida en pequeños 'chunks' (paquetes).
    """
    # Acepta y valida el apretón de manos (handshake) del WebSocket
    await websocket.accept()
    print("[Twilio WS] Conexión WebSocket establecida con Twilio.")

    # Buffer temporal binario en memoria para ir reuniendo los paquetes de audio
    audio_buffer = bytearray()

    try:
        # Bucle infinito mientras la llamada y la conexión sigan activas
        while True:
            # Recibe el mensaje enviado por Twilio (llega en texto JSON)
            message = await websocket.receive_text()
            data = json.loads(message)
            event = data.get("event")

            # EVENTO 1: Inicio de la transmisión de audio
            if event == "start":
                stream_sid = data.get("streamSid")
                print(f"[Twilio WS] Stream Iniciado (SID: {stream_sid})")

            # EVENTO 2: Llega un bloque de audio de la llamada
            elif event == "media":
                # Twilio envía el audio codificado en formato Base64
                payload = data["media"]["payload"]
                
                # Decodificar el texto Base64 a bytes puros (formato comprimido mu-law de telefonia)
                raw_mulaw = base64.b64decode(payload)

                # Convertir el audio telefónico (mu-law 8kHz) a audio lineal descomprimido PCM 16-bit
                # (formato estándar requerido por Whisper y la mayoría de clasificadores)
                pcm16_data = audioop.ulaw2lin(raw_mulaw, 2)
                
                # Agregar los nuevos bytes descompresionados al buffer acumulativo
                audio_buffer.extend(pcm16_data)

                # REGLA DE PROCESAMIENTO:
                # 8000 Hz x 16 bits (2 bytes por muestra) = 16,000 bytes por segundo.
                # 48,000 bytes equivalen a exactamente 3 segundos de audio acumulado.
                if len(audio_buffer) >= 48000:
                    # Copiamos los bytes acumulados hasta el momento
                    chunk_to_process = bytes(audio_buffer)
                    # Limpiamos el buffer para recibir los siguientes 3 segundos
                    audio_buffer.clear()

                    # ----------------------------------------------------------
                    # CANALIZACIÓN DE ANÁLISIS DE VISHGUARD
                    # ----------------------------------------------------------
                    
                    # Sub-paso A: Transcripción
                    # Aquí se alimentará `chunk_to_process` a Whisper. Por ahora se usa un string simulación:
                    texto_transcrito = "Simulación: Necesitamos confirmación de su clave bancaria por seguridad urgente."

                    # Sub-paso B: Evaluación de Fraude/Vishing
                    # Se llama a VishingAnalyzer que internamente decidirá si usa Groq LLM o la Heurística local
                    resultado = analyzer.analizar_texto(texto_transcrito)
                    await manager.enviar_a(to, resultado)
                    print(f"[VishGuard Analysis]: {resultado}")

                    # Sub-paso C: Persistencia en Base de Datos
                    # Si el nivel de amenaza detectado es riesgoso, se almacena en el historial
                    nivel = resultado.get("nivel_riesgo")
                    if nivel in ["PELIGROSO", "FRAUDE", "MEDIO"]:
                        db = SessionLocal()  # Abre una sesión de base de datos
                        try:
                            # Crea el objeto según el ORM de SQLAlchemy definido en database.py
                            nueva_alerta = AlertHistory(
                                #texto=texto_transcrito,
                                nivel_riesgo=nivel,
                                score=resultado.get("score", 0),
                                recomendacion=resultado.get("recomendacion", "")
                            )
                            db.add(nueva_alerta)  # Guarda el registro
                            db.commit()          # Confirma los cambios en la DB
                        finally:
                            db.close()           # Cierra la sesión para evitar fugas de conexiones

            # EVENTO 3: El usuario o la centralita cuelgan la llamada
            elif event == "stop":
                print("[Twilio WS] Transmisión de audio finalizada por Twilio.")
                if len(audio_buffer) > 0:
                    # procesar el remanente igual que el bloque de arriba (mismo sub-paso A/B/C)
                    pass
                break

    except WebSocketDisconnect:
        print("[Twilio WS] Conexión cerrada de forma abrupta por el cliente/Twilio.")

@router.get("/debug/connections")
def ver_conexiones():
    from core.connection_manager import manager
    return {"conectados": list(manager.active_connections.keys())}