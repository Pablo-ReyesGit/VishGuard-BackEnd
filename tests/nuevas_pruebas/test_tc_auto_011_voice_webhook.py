"""
Caso de Prueba 1: TC-AUTO-011
Nombre: Validación de respuesta TwiML válida en Webhook POST /twilio/voice
Tipo: API / Integración
Prioridad: Alta
"""
import pytest
import xml.etree.ElementTree as ET

@pytest.mark.integration
@pytest.mark.twilio
def test_tc_auto_011_voice_webhook_returns_valid_twiml(client):
    """
    Pasos:
    1. Enviar petición HTTP POST a /twilio/voice con payload de llamada entrante.
    2. Parsear el XML TwiML devuelto.
    3. Verificar configuración del Stream (<Start>, <Dial>).
    """
    payload = {
        "CallSid": "CA1234567890",
        "From": "+50255551234",
        "To": "+18005559999",
        "CallStatus": "ringing"
    }
    
    response = client.post("/twilio/voice", data=payload)
    
    # Aserción 1: HTTP 200 OK y Content-Type XML
    assert response.status_code == 200
    assert "xml" in response.headers.get("content-type", "").lower()
    
    # Aserción 2: Parsear XML raíz <Response>
    root = ET.fromstring(response.text)
    assert root.tag == "Response"
    
    # Aserción 3: Verificar presencia de etiquetas <Start> y <Stream>
    start_tag = root.find("Start")
    assert start_tag is not None
    
    stream_tag = start_tag.find("Stream")
    assert stream_tag is not None
    assert stream_tag.attrib.get("track") == "both_tracks"
    assert "ws" in stream_tag.attrib.get("url", "").lower()
