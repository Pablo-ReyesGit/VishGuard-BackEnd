import re
import pytest
import services.heuristic_engine as engine

CASOS_CRITICOS = [
    (r"\b(cvv|cvc)\b", "dígame el cvv de su tarjeta"),
    (r"numeros? de atr[aá]s", "los números de atrás de la tarjeta"),   # falla hasta corregir el patrón (hallazgo 1)
    (r"tres d[ií]gitos", "los tres dígitos de atrás"),
    (r"16 d[ií]gitos", "los 16 dígitos de la tarjeta"),
    (r"fecha de vencimiento", "ahora la fecha de vencimiento"),
    (r"\b(nip|pin)\b", "dígame su pin"),
    (r"contrase[nñ]a", "necesito su contraseña del banco"),
    (r"\bpassword\b", "dígame el password"),
    (r"clave (din[aá]mica|interbancaria|web|de acceso|de seguridad)", "su clave dinámica por favor"),
    (r"token (m[oó]vil|digital|f[ií]sico)?", "necesito su token móvil"),
    (r"c[oó]digo de (seguridad|confirmaci[oó]n|verificaci[oó]n|6 d[ií]gitos|4 d[ií]gitos)", "el código de verificación"),
    (r"mensaje de texto con el c[oó]digo", "le llegó un mensaje de texto con el código"),
    (r"d[ií]cteme el c[oó]digo", "dícteme el código"),
    (r"d[ií]cteme su clave", "dícteme su clave"),
    (r"teclee su pin", "teclee su pin ahora"),
    (r"tarjeta de (cr[eé]dito|d[eé]bito)", "los datos de su tarjeta de crédito"),
]

CASOS_URGENCIA = [
    (r"bloqueo de cuenta", "hay un bloqueo de cuenta"),
    (r"cuenta suspendida", "tiene la cuenta suspendida"),
    (r"fondos congelados", "hay fondos congelados"),
    (r"cargo no reconocido", "vemos un cargo no reconocido"),
    (r"transferencia sospechosa", "detectamos una transferencia sospechosa"),
    (r"movimiento inusual", "hubo un movimiento inusual"),
    (r"compra no autorizada", "registramos una compra no autorizada"),
    (r"orden de embargo", "tiene una orden de embargo"),
    (r"demanda legal", "habrá una demanda legal"),
    (r"retenci[oó]n de saldo", "procede la retención de saldo"),
    (r"cancelar el cargo", "para cancelar el cargo"),
    (r"tenemos a tu (hijo|hija|mam[aá]|pap[aá]|familiar)", "tenemos a tu hijo"),
    (r"no cuelgue la llamada", "no cuelgue la llamada"),
]

@pytest.mark.parametrize("patron,texto", CASOS_CRITICOS)
def test_heur_01_patrones_criticos_fraude(patron, texto):
    assert re.search(patron, texto, re.IGNORECASE)

@pytest.mark.parametrize("patron,texto", CASOS_URGENCIA)
def test_heur_02_patrones_urgencia(patron, texto):
    assert re.search(patron, texto, re.IGNORECASE)

def test_heur_01b_cada_patron_tiene_caso():
    assert {p for p, _ in CASOS_CRITICOS} == set(engine.PATRONES_CRITICOS_FRAUDE)
    assert {p for p, _ in CASOS_URGENCIA} == set(engine.PATRONES_COACCION_URGENCIA)