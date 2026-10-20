"""SPRINT 1 - Privacidad, logs, memoria volátil y configuración segura.
Cubre: T1 PIISanitizer (fail-closed) | T2 LogSanitizerFilter | T3 VolatileAudioBuffer
       | JWT/config (SecuritySettings) | hashing argon2.
Incluye los caminos deseados y no deseados originales + regresiones de la auditoría.
"""
import logging
import sys
import time

import pytest
from core.config_security import SecuritySettings
from core.log_sanitizer import LogSanitizerFilter, scrub
from core.passwords import hash_password, verify_password, needs_rehash
from modules.Security.pii_sanitizer import PIISanitizer, SanitizationError, luhn_ok
from modules.Security.volatile_buffer import VolatileAudioBuffer, BufferClosed, BufferLimitExceeded

S = PIISanitizer()


def test_happy_path_buffer_toma_datos_y_borra_remanente():
    buf = VolatileAudioBuffer(max_seconds=1, bytes_per_second=100)
    buf.append(b"abcdefgh")
    assert buf.take(3) == b"abc"
    assert bytes(buf.peek()) == b"defgh"
    buf.close()
    assert len(buf) == 0


@pytest.mark.parametrize("value", [None, 7, b"texto", {"texto":"hola"}])
def test_e01_entrada_no_string_bloquea(value):
    with pytest.raises(SanitizationError): S.sanitize(value)


def test_e02_tarjeta_luhn_se_enmascara():
    assert luhn_ok("4539148803436467")
    assert "[TARJETA]" in S.sanitize("tarjeta 4539 1488 0343 6467")


def test_e03_correo_iban_y_pin_no_salen_en_claro():
    out = S.sanitize("iban ES9121000418450200051332 correo juan@mail.com mi pin es 4821")
    assert "ES91" not in out and "juan@mail.com" not in out and "4821" not in out
    assert "pin" in out.lower()


def test_e04_numeros_dictados_se_enmascaran():
    out = S.sanitize("mi cuenta es uno dos tres cuatro cinco seis")
    assert "uno dos" not in out


def test_e05_texto_normal_se_conserva():
    text = "hola mamá, ya voy para la casa"
    assert S.sanitize(text) == text


def test_e06_salida_llm_tambien_se_sanitiza_recursivamente():
    out = S.sanitize_output({"mensaje_alerta":"correo a@b.co y pin 4821", "items":["llama +502 5555 1234"]})
    assert "a@b.co" not in out["mensaje_alerta"] and "4821" not in out["mensaje_alerta"]
    assert "+502 5555 1234" not in out["items"][0]


def test_e23_buffer_supera_capacidad_y_no_corrompe_datos_previos():
    buf = VolatileAudioBuffer(max_seconds=1, bytes_per_second=100)
    buf.append(b"a" * 60)
    with pytest.raises(BufferLimitExceeded): buf.append(b"b" * 50)
    assert len(buf) == 60 and bytes(buf.peek()) == b"a" * 60


def test_e24_buffer_cerrado_rechaza_escritura_y_lectura_consumidora():
    buf = VolatileAudioBuffer(max_seconds=1, bytes_per_second=100)
    buf.append(b"secret")
    buf.close()
    with pytest.raises(BufferClosed): buf.append(b"x")
    with pytest.raises(BufferClosed): buf.take(1)


def test_e25_cierre_buffer_es_idempotente():
    buf = VolatileAudioBuffer(); buf.append(b"secret"); buf.close(); buf.close()
    assert len(buf) == 0


def test_e26_tomar_mas_bytes_que_disponibles_no_falla():
    buf = VolatileAudioBuffer(max_seconds=1, bytes_per_second=100)
    buf.append(b"abc")
    assert buf.take(100) == b"abc" and len(buf) == 0


def test_e31_secret_key_corta_se_rechaza():
    with pytest.raises(Exception): SecuritySettings(SECRET_KEY="corta")


def test_e32_cors_wildcard_en_produccion_se_rechaza():
    with pytest.raises(Exception): SecuritySettings(SECRET_KEY="s"*40, ENVIRONMENT="prod", CORS_ORIGINS=["*"])


def test_e33_documentacion_desactivada_en_produccion():
    settings = SecuritySettings(SECRET_KEY="s"*40, ENVIRONMENT="prod")
    assert settings.docs_url is None


def test_e34_hash_password_no_guarda_clave_en_claro_y_verifica():
    hashed = hash_password("Secreta123!")
    assert hashed != "Secreta123!"
    assert verify_password("Secreta123!", hashed)
    assert not verify_password("incorrecta", hashed)
    assert isinstance(needs_rehash(hashed), bool)


def test_e35_log_scrubber_oculta_jwt_token_email_y_telefono():
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abc123"
    text = scrub(f"/ws?token={jwt} user=a@b.com llama +502 5555 1234")
    assert jwt not in text and "token=[MASK]" in text
    assert "a@b.com" not in text and "+502 5555 1234" not in text


def test_e36_log_filter_limpia_mensaje_formateado_y_args():
    record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0,
                               "api_key=%s correo=%s", ("abc-secret", "a@b.com"), None)
    LogSanitizerFilter().filter(record)
    output = record.getMessage()
    assert "abc-secret" not in output and "a@b.com" not in output


def test_e37_log_filter_suprime_traceback_con_secreto():
    try:
        raise ValueError("api_key=AIzaSyA1234567890abcdefghijklmnopqrstuv")
    except ValueError:
        import sys
        record = logging.LogRecord("app", logging.ERROR, "", 0, "falló", (), sys.exc_info())
    LogSanitizerFilter().filter(record)
    assert "AIzaSy" not in (record.exc_text or "") and record.exc_info is None

# ===================== REGRESIONES DE LA AUDITORÍA (Sprint 1) =====================

@pytest.mark.parametrize("texto,filtrado", [
    ("mi dpi es 2345 67890 0101", "2345 67890"),     # DPI con espacios (13 dígitos)
    ("mi celular es 5555-1234", "5555-1234"),         # teléfono local de 8 dígitos
    ("mi celular es 5555 1234", "5555 1234"),
    ("folio 1234 5678 9012 3456", "1234 5678"),       # 16 dígitos que NO pasan Luhn
    ("nací el 12-03-1990", "12-03-1990"),
])
def test_a01_digitos_con_separadores_no_salen_en_claro(texto, filtrado):
    assert filtrado not in S.sanitize(texto)


def test_a02_tarjeta_no_se_come_el_espacio_siguiente():
    assert S.sanitize("tarjeta 4539 1488 0343 6467 con vencimiento") == "tarjeta [TARJETA] con vencimiento"


@pytest.mark.parametrize("texto", ["pagué 1500 quetzales el 15", "hoy son las 10:30", "mi tarjeta termina en 6467"])
def test_a03_numeros_cortos_no_generan_falsos_positivos(texto):
    assert S.sanitize(texto) == texto


def test_a04_sanitizador_resiste_entrada_gigante_sin_colgarse():
    t0 = time.time()
    S.sanitize("1 " * 100_000); S.sanitize("uno " * 100_000)
    assert time.time() - t0 < 3


def test_a05_entorno_por_defecto_es_produccion(monkeypatch):
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    s = SecuritySettings(SECRET_KEY="s" * 40, _env_file=None)
    assert s.ENVIRONMENT == "prod" and s.docs_url is None


def test_a06_log_no_enmascara_marcas_de_hora_ip_ni_latencias():
    linea = '2026-10-09 23:47:01 INFO 192.168.1.10:5555 - "GET /health" 200 latencia 0.123456789 s'
    assert scrub(linea) == linea


def test_a07_log_si_enmascara_telefono_local_y_con_prefijo():
    assert "5555-1234" not in scrub("llamó al 5555-1234")
    assert "+502 5555 1234" not in scrub("llamó al +502 5555 1234")


def test_a08_log_filter_con_args_en_diccionario():
    rec = logging.LogRecord("x", logging.INFO, "", 0, "k=%(k)s", ({"k": "a@b.com"},), None)
    LogSanitizerFilter().filter(rec)
    assert "a@b.com" not in rec.getMessage()


def test_a09_buffer_conserva_integridad_tras_take():
    buf = VolatileAudioBuffer(max_seconds=1, bytes_per_second=100)
    buf.append(bytes(range(50))); buf.take(10)
    assert bytes(buf.peek()) == bytes(range(10, 50))


def test_a10_vista_peek_queda_en_cero_tras_close():
    buf = VolatileAudioBuffer(max_seconds=1, bytes_per_second=100)
    buf.append(b"secreto"); vista = buf.peek(); buf.close()
    assert bytes(vista) == b"\x00" * 7
