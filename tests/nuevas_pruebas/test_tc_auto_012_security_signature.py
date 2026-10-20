"""
Caso de Prueba 2: TC-AUTO-012-SECURITY
Nombre: Validación estricta de firma HMAC X-Twilio-Signature y rechazo de peticiones manipuladas
Tipo: Seguridad / API
Prioridad: Alta
"""
import pytest

@pytest.mark.security
@pytest.mark.twilio
def test_tc_auto_012_tampered_body_is_rejected(client):
    """
    Pasos:
    1. Enviar petición POST con firma calculada para CA_ORIGINAL pero enviando CA_MANIPULADO.
    2. Verificar respuesta del webhook (HTTP 403 Forbidden).
    """
    payload_manipulado = {
        "CallSid": "CA_MANIPULADO_9999",
        "From": "+50255551234",
        "To": "+18005559999"
    }
    
    # Firma HMAC falsificada o calculada para un cuerpo diferente
    headers = {
        "X-Twilio-Signature": "FirmaHMACInvalidaOAlterada123456="
    }
    
    response = client.post("/twilio/voice", data=payload_manipulado, headers=headers)
    
    # Aserción: Rechazo inmediato con HTTP 403 Forbidden y sin contenido TwiML
    assert response.status_code == 403
    assert "<Response>" not in response.text
