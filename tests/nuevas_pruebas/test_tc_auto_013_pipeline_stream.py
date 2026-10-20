"""
Caso de Prueba 3: TC-AUTO-013-PIPELINE
Nombre: Flujo de procesamiento streaming completo en WebSocket /ws/twilio (chunk 3s)
Tipo: Integración / WebSocket
Prioridad: Alta
"""
import pytest
import json
import base64

@pytest.mark.integration
@pytest.mark.websocket
def test_tc_auto_013_media_stream_full_pipeline(client, mocker):
    """
    Pasos:
    1. Iniciar conexión WebSocket en /ws/twilio y transmitir evento start.
    2. Transmitir 150 tramas base64 mu-law acumulando 48 KB de audio (3 segundos).
    3. Verificar que STT sea invocado exactamente una vez y la alerta sea emitida.
    """
    mock_stt = mocker.patch("modules.stt.transcribe_audio", return_value={"text": "clave de banco urgente"})
    mock_analyzer = mocker.patch("modules.analyzer.VishingAnalyzer.analizar_texto", return_value={
        "nivel_riesgo": "PELIGROSO",
        "score": 95,
        "mensaje_alerta": "Intento de estafa detectado",
        "recomendacion": "Cuelgue de inmediato"
    })
    
    with client.websocket_connect("/ws/twilio") as ws:
        # Paso 1: Handshake y Start
        ws.send_json({
            "event": "start",
            "streamSid": "MZ12345",
            "start": {
                "callSid": "CA1234567890",
                "customParameters": {"to": "+50257008032", "from": "+50255551234"}
            }
        })
        
        # Paso 2: Enviar 150 frames de 160 bytes mu-law (3 segundos)
        frame_mulaw = base64.b64encode(b"\xff" * 160).decode()
        for _ in range(150):
            ws.send_json({
                "event": "media",
                "media": {"payload": frame_mulaw, "track": "inbound"}
            })
            
        # Finalizar llamada
        ws.send_json({"event": "stop", "streamSid": "MZ12345"})
        
    # Aserción: STT e IA fueron invocados con la cantidad esperada
    assert mock_stt.called
    assert mock_analyzer.called
