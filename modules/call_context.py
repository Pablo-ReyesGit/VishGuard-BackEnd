"""Contexto conversacional de UNA llamada de VishGuard.

El análisis de IA recibe fragmentos sueltos de UN hablante. Un vishing de tarjeta se
reparte entre pistas y bloques: el llamante pide "el número de la tarjeta de crédito" y
el receptor dicta los dígitos 10 s después, en 3 o más bloques de ~6 dígitos. Ningún
fragmento por sí solo parece peligroso.

ContextoLlamada guarda los últimos `ventana_s` segundos de ambas pistas y detecta la
combinación "el llamante pidió un dato financiero" + "el receptor dictó >= N dígitos".
Es una regla de piso, independiente del LLM: si se cumple, la alerta sube a PELIGROSO.

Uso (en twilio_stream.py):
    contexto = ContextoLlamada()                       # una por llamada
    contexto.agregar(hablante, texto)                  # tras transcribir cada bloque
    if contexto.senal_fraude():
        resultado = contexto.elevar(resultado)
"""

import os
import re
import time
import unicodedata
from collections import deque
from typing import Optional

_PALABRAS_DIGITO = frozenset(
    {"cero", "uno", "una", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve"}
)

# Texto ya normalizado (minúsculas, sin tildes). "credit" cubre errores de ASR como
# "terreno de crédito"; no hace falta que "tarjeta" se transcriba bien.
_RE_PEDIDO = re.compile(
    r"tarjet|credit|debit|\bcvv\b|\bcvc\b|codigo de seguridad|vencimiento|expiracion"
    r"|\bclave\b|\bpin\b|\bnip\b|contrasena|\btoken\b|numero de cuenta"
)

RECOMENDACION_DEFECTO = (
    "🛑 ¡ALERTA DE FRAUDE! Solicitud de datos confidenciales detectada. Cuelgue de inmediato."
)


def _norm(texto: str) -> str:
    nfd = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def _tok(token: str) -> str:
    return re.sub(r"[^\w]", "", _norm(token))


def _solape(previos: list[str], nuevos: list[str], maximo: int = 6) -> int:
    """Cuántas palabras del inicio de `nuevos` ya estaban al final de `previos`.

    Los bloques se solapan ~1 s de audio, así que las últimas palabras de un bloque
    suelen repetirse al principio del siguiente. Sin quitarlas, los dígitos del
    borde se contarían dos veces.
    """
    for k in range(min(maximo, len(previos), len(nuevos)), 0, -1):
        if [_tok(t) for t in previos[-k:]] == [_tok(t) for t in nuevos[:k]]:
            return k
    return 0


UMBRAL_PELIGROSO = 70   # score >= 70 -> PELIGROSO (el LLM devuelve ~85-90 en fraude claro)
UMBRAL_MEDIO = 40       # score >= 40 -> MEDIO


class ContextoLlamada:
    def __init__(
        self,
        ventana_s: float = 45.0,
        min_digitos: int = 6,
        score_minimo: int = 85,
        digitos_de: Optional[str] = "env",
    ):
        """`digitos_de`: quién debe dictar los dígitos para que cuente como fraude.

        "receptor" (producto real: la persona protegida recibe la llamada del estafador),
        "llamante", o None / "cualquiera" (útil en pruebas donde tú haces los dos papeles).
        Con "env" (defecto) se lee VISHGUARD_DIGITOS_DE (defecto "receptor").
        """
        self.ventana_s = ventana_s
        self.min_digitos = min_digitos
        self.score_minimo = score_minimo
        if digitos_de == "env":
            digitos_de = os.getenv("VISHGUARD_DIGITOS_DE", "receptor").strip().lower()
        self.digitos_de = None if digitos_de in (None, "", "cualquiera", "todos", "any") else digitos_de
        self._score_llamada = 0
        self._eventos: deque[tuple[float, str, str]] = deque()   # (instante, hablante, texto)
        self._ultimo: dict[str, list[str]] = {}                   # últimas palabras por hablante

    # ------------------------------------------------------------------
    def agregar(self, hablante: str, texto: str, ahora: Optional[float] = None) -> None:
        ahora = time.monotonic() if ahora is None else ahora
        tokens = texto.split()
        k = _solape(self._ultimo.get(hablante, []), tokens)
        self._ultimo[hablante] = tokens
        nuevo = " ".join(tokens[k:])
        if nuevo:
            self._eventos.append((ahora, hablante, nuevo))
        self._purgar(ahora)

    def _purgar(self, ahora: float) -> None:
        while self._eventos and ahora - self._eventos[0][0] > self.ventana_s:
            self._eventos.popleft()

    # ------------------------------------------------------------------
    @staticmethod
    def _contar_digitos(texto: str) -> int:
        """Cuenta cifras dictadas. Las palabras ("cinco", "siete") solo cuentan dentro de una
        racha de 2 o más tokens numéricos seguidos: así "una crema" o "uno de ellos" no suman."""
        tokens = re.sub(r"[^\w\s]", " ", _norm(texto)).split()
        total, racha = 0, []
        for tok in tokens + [None]:
            if tok is not None and (tok.isdigit() or tok in _PALABRAS_DIGITO):
                racha.append(tok)
                continue
            if racha:
                for t in racha:
                    if t.isdigit():
                        total += len(t)
                    elif len(racha) >= 2:
                        total += 1
                racha = []
        return total

    def digitos_dictados(self, ahora: Optional[float] = None) -> int:
        """Dígitos (cifras o palabras) dictados por `digitos_de` dentro de la ventana."""
        self._purgar(time.monotonic() if ahora is None else ahora)
        return sum(
            self._contar_digitos(t)
            for _, h, t in self._eventos
            if self.digitos_de is None or h == self.digitos_de
        )

    def hubo_pedido(self, ahora: Optional[float] = None) -> bool:
        """¿Alguien mencionó un dato financiero (tarjeta, CVV, clave...) dentro de la ventana?

        Se acepta de cualquiera de los dos: el estafador lo pide ("dame la tarjeta") o la
        víctima lo anuncia ("te voy a dar el número de tarjeta"). Lo decisivo es que el
        receptor (la persona protegida) termine dictando dígitos.
        """
        self._purgar(time.monotonic() if ahora is None else ahora)
        return any(_RE_PEDIDO.search(_norm(t)) for _, _h, t in self._eventos)

    def senal_fraude(self, ahora: Optional[float] = None) -> bool:
        return self.hubo_pedido(ahora) and self.digitos_dictados(ahora) >= self.min_digitos

    # ------------------------------------------------------------------
    def transcripcion(self, ahora: Optional[float] = None, max_chars: int = 1200) -> str:
        """Diálogo reciente de AMBOS lados, etiquetado, para dárselo al LLM como contexto:

            LLAMANTE: hola somos del banco, necesitamos un número de tarjeta
            RECEPTOR: el número es 1 1 1 2 ...
        """
        self._purgar(time.monotonic() if ahora is None else ahora)
        lineas: list[list[str]] = []
        for _, h, t in self._eventos:
            etiqueta = h.upper()
            if lineas and lineas[-1][0] == etiqueta:
                lineas[-1][1] += " " + t
            else:
                lineas.append([etiqueta, t])
        return "\n".join(f"{e}: {t}" for e, t in lineas)[-max_chars:]

    def acumular(self, resultado: dict) -> dict:
        """Añade `score_llamada` y `nivel_llamada`: el riesgo de la LLAMADA, que no baja
        porque el último fragmento (p. ej. "mañana") sea inocuo. `score` y `nivel_riesgo`
        siguen siendo los del fragmento."""
        try:
            score = int(resultado.get("score") or 0)
        except (TypeError, ValueError):
            score = 0
        self._score_llamada = max(self._score_llamada, score)
        if self._score_llamada >= UMBRAL_PELIGROSO:
            nivel = "PELIGROSO"
        elif self._score_llamada >= UMBRAL_MEDIO:
            nivel = "MEDIO"
        else:
            nivel = "BAJO"
        return {**resultado, "score_llamada": self._score_llamada, "nivel_llamada": nivel}

    # ------------------------------------------------------------------
    def elevar(self, resultado: dict) -> dict:
        """Devuelve una copia del resultado del analizador elevada a PELIGROSO."""
        r = dict(resultado)
        try:
            score = int(r.get("score") or 0)
        except (TypeError, ValueError):
            score = 0
        ya_peligroso = r.get("nivel_riesgo") == "PELIGROSO"

        r["score"] = max(score, self.score_minimo)
        r["nivel_riesgo"] = "PELIGROSO"

        motivo = "solicitud de datos de tarjeta + dígitos dictados"
        patrones = r.get("patrones_detectados")
        if isinstance(patrones, list):
            if motivo not in patrones:
                patrones = patrones + [motivo]
        elif isinstance(patrones, str) and patrones:
            patrones = patrones if motivo in patrones else f"{patrones}, {motivo}"
        else:
            patrones = motivo
        r["patrones_detectados"] = patrones

        if not ya_peligroso or not r.get("recomendacion"):
            r["recomendacion"] = RECOMENDACION_DEFECTO
        return r