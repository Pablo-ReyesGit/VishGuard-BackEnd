import re
import time

# 🛑 1. Extracción Crítica de Datos Sensibles (+80 pts directo -> PELIGROSO)

PATRONES_CRITICOS_FRAUDE = [
    r"\b(cvv|cvc)\b",
    r"numeros? de atr[aá]s",
    r"tres d[ií]gitos",
    r"16 d[ií]gitos",
    r"fecha de vencimiento",
    r"\b(nip|pin)\b",
    r"contrase[nñ]a",
    r"\bpassword\b",
    r"clave (din[aá]mica|interbancaria|web|de acceso|de seguridad)",
    r"token (m[oó]vil|digital|f[ií]sico)?",
    r"c[oó]digo de (seguridad|confirmaci[oó]n|verificaci[oó]n|6 d[ií]gitos|4 d[ií]gitos)",
    r"mensaje de texto con el c[oó]digo",
    r"d[ií]cteme el c[oó]digo",
    r"d[ií]cteme su clave",
    r"teclee su pin",
    r"tarjeta de (cr[eé]dito|d[eé]bito)"
]

# 🟠 2. Coacción / Coincidencias de Urgencia Bancaria (+35 pts)
PATRONES_COACCION_URGENCIA = [
    r"bloqueo de cuenta",
    r"cuenta suspendida",
    r"fondos congelados",
    r"cargo no reconocido",
    r"transferencia sospechosa",
    r"movimiento inusual",
    r"compra no autorizada",
    r"orden de embargo",
    r"demanda legal",
    r"retenci[oó]n de saldo",
    r"cancelar el cargo",
    r"tenemos a tu (hijo|hija|mam[aá]|pap[aá]|familiar)",
    r"no cuelgue la llamada"
]

# 🟠 3. Suplantación Institucional (+25 pts)
PATRONES_INSTITUCIONES = [
    r"banco (santander|bbva|banamex|bac|bi|banrural|galicia|itau|bancolombia|azteca|falabella|scotiabank|hsbc|bcp|banorte)",
    r"departamento de seguridad",
    r"prevenci[oó]n de fraudes",
    r"asesor financiero",
    r"ejecutivo de cuenta bancaria",
    r"paquete retenido en aduana",
    r"entrega fallida de mercado libre",
    r"soporte de microsoft",
    r"instale anydesk",
    r"instale teamviewer"
]

# 🟡 4. Ganchos Comerciales / Premios (+20 pts)
PATRONES_COMERCIAL = [
    r"ganador de un (premio|carro|auto|viaje|sorteo)",
    r"cr[eé]dito preaprobado",
    r"pr[eé]stamo inmediato",
    r"actualizar su expediente",
    r"confirmar sus datos personales",
    r"reclame su recompensa"
]

# 🟢 5. Conversación Segura / Cotidiana (Inmunidad a falsos positivos)
PATRONES_SEGUROS = [
    r"hola (mam[aá]|pap[aá]|hijo|hija|abuela|abuelo|t[ií]a|t[ií]o|primo|prima|amor|amigo|amiga|hermano|hermana|madre|padre|mi vida)",
    r"c[oó]mo est[aá]s",
    r"qu[eé] tal",
    r"c[oó]mo te fue",
    r"a qu[eé] hora (llegas|vienes|comemos|cenamos|almorzamos)",
    r"ya voy para",
    r"estoy en (el tr[aá]fico|el trabajo|la escuela|la casa)",
    r"voy a comprar",
    r"te quiero",
    r"te amo",
    r"nos vemos",
    r"cu[ií]date",
    r"qu[eé] vas a querer",
    r"buenos d[ií]as",
    r"buenas tardes",
    r"buenas noches"
]
def evaluar_amenaza(texto_original: str):
    frase = texto_original.lower().strip()
    
    score = 0
    hallazgos = []

    # 1. Comprobar si es charla cotidiana segura
    es_cotidiana = any(re.search(patron, frase) for patron in PATRONES_SEGUROS)

    # 2. Evaluar petición crítica de credenciales
    pide_credenciales = False
    for patron in PATRONES_CRITICOS_FRAUDE:
        if re.search(patron, frase):
            score += 85
            pide_credenciales = True
            hallazgos.append("Solicitud explícita de tarjeta, PIN, CVV o código SMS.")
            break

    # 3. Evaluar coacción / urgencia
    for patron in PATRONES_COACCION_URGENCIA:
        if re.search(patron, frase):
            score += 35
            hallazgos.append("Generación de urgencia, cargos no reconocidos o amenazas.")
            break

    # 4. Evaluar suplantación institucional
    for patron in PATRONES_INSTITUCIONES:
        if re.search(patron, frase):
            score += 25
            hallazgos.append("Mención de entidad financiera, paquetería o soporte.")
            break

    # 5. Evaluar ganchos comerciales
    for patron in PATRONES_COMERCIAL:
        if re.search(patron, frase):
            score += 20
            hallazgos.append("Gancho de premio o confirmación de datos.")
            break

    # Si es charla cotidiana y NO pidió credenciales críticas, amortiguar a 0
    if es_cotidiana and not pide_credenciales:
        score = 0
        hallazgos = []

    # Normalizar score a 0 - 100
    score = min(100, max(0, score))

    # Clasificación estricta por rangos
    if score >= 75:
        nivel = "PELIGROSO"
        recomendacion = "🛑 ¡ALERTA DE FRAUDE! Solicitud de datos confidenciales detectada. Cuelgue de inmediato."
    elif score >= 40:
        nivel = "MEDIO"
        recomendacion = "⚠️ LLAMADA SOSPECHOSA: Se detectaron motivos de alerta o presión. No proporcione información personal."
    else:
        nivel = "BAJO"
        recomendacion = "🛡️ LLAMADA SEGURA: Conversación cotidiana sin indicadores de riesgo."

    return nivel, score, recomendacion, hallazgos

def evaluar_amenaza_como_json(texto: str) -> dict:
    nivel, score, recomendacion, hallazgos = evaluar_amenaza(texto)
    return {
        "nivel_riesgo": nivel,
        "score": score,
        "patrones_detectados": hallazgos,
        "frase_critica": texto[:120],  # o extraer el fragmento que matcheó
        "recomendacion": recomendacion
    }