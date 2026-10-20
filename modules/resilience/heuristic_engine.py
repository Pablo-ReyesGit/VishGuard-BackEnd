"""T7 - Motor heurístico local + regla de piso de riesgo.

Reutiliza las listas regex de tu services/heuristic_engine.py (no se duplican).
Cambios vs. la versión original:
  * recoge TODAS las categorías y el fragmento que coincidió (frase_critica real)
  * la "inmunidad" de charla cotidiana ya NO anula coacción/institución (evasión trivial)
  * una palabra sensible SOLA ("tarjeta de crédito", "contraseña") ya no da 85: solo pesa
    85 si es una PETICIÓN explícita o está corroborada por otra categoría. Como el piso
    max(LLM, heurístico) no se puede corregir aguas abajo, evitamos amplificar falsos positivos.
  * umbrales centralizados (los usa también el piso)
"""
import re
from services.heuristic_engine import (
    PATRONES_CRITICOS_FRAUDE, PATRONES_COACCION_URGENCIA, PATRONES_INSTITUCIONES,
    PATRONES_COMERCIAL, PATRONES_SEGUROS,
)

UMBRAL_PELIGROSO = 70
UMBRAL_MEDIO = 40
PUNTOS_CRITICO_CONFIRMADO = 85
PUNTOS_CRITICO_AISLADO = 30      # mención sin petición ni corroboración -> queda en BAJO

_PETICION = re.compile(
    r"(d[ií]game|d[ií]ctame|d[ií]cteme|d[ií]me|d[ií]game|proporcione|proporci[oó]name|env[ií]e|env[ií]ame|"
    r"facilite|necesito|necesitamos|confirme|conf[ií]rmame|teclee|ingrese|comparta|comp[aá]rtame|"
    r"p[aá]same|p[aá]seme|me (puede|puedes) (dar|decir|pasar)|cu[aá]l es (su|tu)|indique|ind[ií]queme)"
    r".{0,60}(pin|nip|cvv|cvc|contrase|clave|c[oó]digo|token|tarjeta|n[uú]meros? de atr[aá]s|d[ií]gitos)"
    r"|(su|tu) (pin|nip|cvv|clave|contrase[nñ]a|token)\b",
    re.IGNORECASE,
)

_RECOMENDACIONES = {
    "PELIGROSO": "🛑 ¡ALERTA DE FRAUDE! Solicitud de datos confidenciales detectada. Cuelgue de inmediato.",
    "MEDIO": "⚠️ LLAMADA SOSPECHOSA: Se detectaron motivos de alerta o presión. No proporcione información personal.",
    "BAJO": "🛡️ LLAMADA SEGURA: Conversación cotidiana sin indicadores de riesgo.",
}

def nivel_desde_score(score: int) -> str:
    if score >= UMBRAL_PELIGROSO:
        return "PELIGROSO"
    if score >= UMBRAL_MEDIO:
        return "MEDIO"
    return "BAJO"

def recomendacion_para(nivel: str) -> str:
    return _RECOMENDACIONES[nivel]

_SECUNDARIAS = [
    (PATRONES_COACCION_URGENCIA, 35, "Generación de urgencia, cargos no reconocidos o amenazas."),
    (PATRONES_INSTITUCIONES, 25, "Mención de entidad financiera, paquetería o soporte."),
    (PATRONES_COMERCIAL, 20, "Gancho de premio o confirmación de datos."),
]
_DESC_CRITICO = "Solicitud explícita de tarjeta, PIN, CVV o código SMS."
_DESC_CRITICO_AISLADO = "Mención de dato sensible sin petición clara."

def _primera(patrones, frase):
    for p in patrones:
        m = re.search(p, frase)
        if m:
            return m
    return None

class HeuristicEngine:
    def evaluate(self, texto: str) -> dict:
        frase = texto.lower().strip()
        score, hallazgos, fragmento = 0, [], ""

        sec = []
        for patrones, pts, desc in _SECUNDARIAS:
            m = _primera(patrones, frase)
            if m:
                sec.append((pts, desc, m.group(0)))
        crit = _primera(PATRONES_CRITICOS_FRAUDE, frase)
        peticion = _PETICION.search(frase)

        if crit or peticion:
            confirmado = bool(peticion) or bool(sec)
            score += PUNTOS_CRITICO_CONFIRMADO if confirmado else PUNTOS_CRITICO_AISLADO
            hallazgos.append(_DESC_CRITICO if confirmado else _DESC_CRITICO_AISLADO)
            fragmento = (peticion or crit).group(0)
        for pts, desc, frag in sec:
            score += pts
            hallazgos.append(desc)
            fragmento = fragmento or frag

        senal_fuerte = bool(crit or peticion or any(p >= 25 for p, _, _ in sec))
        if any(re.search(p, frase) for p in PATRONES_SEGUROS) and not senal_fuerte:
            score, hallazgos, fragmento = 0, [], ""

        score = max(0, min(100, score))
        nivel = nivel_desde_score(score)
        return {
            "nivel_riesgo": nivel,
            "score": score,
            "patrones_detectados": hallazgos,
            "frase_critica": fragmento[:120],
            "recomendacion": recomendacion_para(nivel),
            "mensaje_alerta": hallazgos[0] if hallazgos else "Sin indicadores de riesgo",
        }

def aplicar_piso(score_llm: int, score_heuristico: int) -> int:
    """score_final = max(score_LLM, score_heuristico)"""
    return max(int(score_llm), int(score_heuristico))
