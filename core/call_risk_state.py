from collections import deque
import os
import time
from typing import Callable, Iterable, Optional

from modules.resilience.heuristic_engine import (
    UMBRAL_MEDIO,
    UMBRAL_PELIGROSO,
    nivel_desde_score,
    recomendacion_para,
)

CONTEXTO_MAX_FRAGMENTOS = int(os.getenv("CONTEXTO_MAX_FRAGMENTOS", "12"))
CONTEXTO_MAX_SEG = float(os.getenv("CONTEXTO_MAX_SEG", "60"))
RIESGO_DECAIMIENTO_PTS_SEG = float(os.getenv("RIESGO_DECAIMIENTO_PTS_SEG", "1.0"))
RIESGO_BAJADA_PELIGROSO = float(os.getenv("RIESGO_BAJADA_PELIGROSO", "50"))
RIESGO_PERMANENCIA_PELIGROSO_SEG = float(os.getenv("RIESGO_PERMANENCIA_PELIGROSO_SEG", "20"))
RIESGO_BAJADA_MEDIO = float(os.getenv("RIESGO_BAJADA_MEDIO", "25"))
RIESGO_PERMANENCIA_MEDIO_SEG = float(os.getenv("RIESGO_PERMANENCIA_MEDIO_SEG", "10"))

_ORDEN_NIVEL = {"BAJO": 0, "MEDIO": 1, "PELIGROSO": 2}

_MENSAJES_POR_NIVEL = {
    "PELIGROSO": "Posible fraude detectado en la llamada",
    "MEDIO": "Se mantienen indicadores de precaución en la llamada",
    "BAJO": "Sin indicadores de riesgo",
}


class EstadoRiesgoLlamada:
    """Estado de riesgo acumulado y ventana de contexto por llamada (síncrono)."""

    def __init__(
        self,
        call_id: Optional[str] = None,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self.call_id: Optional[str] = call_id
        self._clock = clock

        self.contexto_max_fragmentos = int(
            os.getenv("CONTEXTO_MAX_FRAGMENTOS", str(CONTEXTO_MAX_FRAGMENTOS))
        )
        self.contexto_max_seg = float(
            os.getenv("CONTEXTO_MAX_SEG", str(CONTEXTO_MAX_SEG))
        )
        self.decaimiento_pts_seg = float(
            os.getenv("RIESGO_DECAIMIENTO_PTS_SEG", str(RIESGO_DECAIMIENTO_PTS_SEG))
        )
        self.bajada_peligroso = float(
            os.getenv("RIESGO_BAJADA_PELIGROSO", str(RIESGO_BAJADA_PELIGROSO))
        )
        self.permanencia_peligroso_seg = float(
            os.getenv(
                "RIESGO_PERMANENCIA_PELIGROSO_SEG",
                str(RIESGO_PERMANENCIA_PELIGROSO_SEG),
            )
        )
        self.bajada_medio = float(
            os.getenv("RIESGO_BAJADA_MEDIO", str(RIESGO_BAJADA_MEDIO))
        )
        self.permanencia_medio_seg = float(
            os.getenv(
                "RIESGO_PERMANENCIA_MEDIO_SEG",
                str(RIESGO_PERMANENCIA_MEDIO_SEG),
            )
        )

        ahora = self._now()
        self.historial: deque[tuple[str, str, float]] = deque()
        self.score_llamada: float = 0.0
        self.nivel_llamada: str = "BAJO"
        self.t_nivel_desde: float = ahora
        self.t_ultimo_update: float = ahora

        self.score_max: int = 0
        self.nivel_max: str = "BAJO"
        self.indicadores: list[str] = []

        self.mensaje_alerta: str = _MENSAJES_POR_NIVEL["BAJO"]
        self.recomendacion: str = recomendacion_para("BAJO")
        self._score_mensaje: float = 0.0

    def _now(self) -> float:
        return self._clock() if self._clock is not None else time.monotonic()

    def _podar_historial(self, ahora: float) -> None:
        while self.historial and (ahora - self.historial[0][2]) > self.contexto_max_seg:
            self.historial.popleft()
        while len(self.historial) > self.contexto_max_fragmentos:
            self.historial.popleft()

    def agregar_contexto(self, hablante: str, texto_sanitizado: str) -> None:
        limpio = (texto_sanitizado or "").strip()
        ahora = self._now()
        if limpio:
            self.historial.append((hablante, limpio, ahora))
        self._podar_historial(ahora)

    def texto_contexto(self) -> str:
        self._podar_historial(self._now())
        lineas = []
        for hablante, texto, _ in self.historial:
            etiqueta = "Llamante" if hablante == "llamante" else (
                "Receptor" if hablante == "receptor" else hablante.capitalize()
            )
            lineas.append(f"{etiqueta}: {texto}")
        return "\n".join(lineas)

    def actualizar(
        self,
        score_fragmento: float | int,
        nivel_fragmento: Optional[str] = None,
        mensaje_alerta: str = "",
        recomendacion: str = "",
        hallazgos: Optional[Iterable[str]] = None,
    ) -> dict:
        ahora = self._now()
        score_frag = float(max(0.0, min(100.0, float(score_fragmento))))
        nivel_frag = nivel_fragmento or nivel_desde_score(round(score_frag))
        if nivel_frag not in _ORDEN_NIVEL:
            nivel_frag = nivel_desde_score(round(score_frag))

        msg_frag = (mensaje_alerta or _MENSAJES_POR_NIVEL[nivel_frag]).strip()
        rec_frag = (recomendacion or recomendacion_para(nivel_frag)).strip()

        # a) Decaimiento lineal por tiempo transcurrido
        dt = max(0.0, ahora - self.t_ultimo_update)
        score_decaido = max(0.0, self.score_llamada - self.decaimiento_pts_seg * dt)

        # b) Score de la llamada
        self.score_llamada = max(score_frag, score_decaido)
        self.t_ultimo_update = ahora

        # c) Nivel con histéresis (usando UMBRAL_MEDIO y UMBRAL_PELIGROSO vía nivel_desde_score)
        nivel_candidato = nivel_desde_score(
            UMBRAL_PELIGROSO if self.score_llamada >= UMBRAL_PELIGROSO else (
                UMBRAL_MEDIO if self.score_llamada >= UMBRAL_MEDIO else 0
            )
        )
        subio_nivel = False

        if _ORDEN_NIVEL[nivel_candidato] > _ORDEN_NIVEL[self.nivel_llamada]:
            self.nivel_llamada = nivel_candidato
            self.t_nivel_desde = ahora
            self.mensaje_alerta = msg_frag
            self.recomendacion = rec_frag
            self._score_mensaje = score_frag
            subio_nivel = True
        else:
            if nivel_frag == self.nivel_llamada and score_frag > self._score_mensaje:
                self.mensaje_alerta = msg_frag
                self.recomendacion = rec_frag
                self._score_mensaje = score_frag

            tiempo_en_nivel = max(0.0, ahora - self.t_nivel_desde)
            if (
                self.nivel_llamada == "PELIGROSO"
                and self.score_llamada < self.bajada_peligroso
                and tiempo_en_nivel >= self.permanencia_peligroso_seg
            ):
                self.nivel_llamada = "MEDIO"
                self.t_nivel_desde = ahora
                self.recomendacion = recomendacion_para("MEDIO")
                self.mensaje_alerta = _MENSAJES_POR_NIVEL["MEDIO"]
                self._score_mensaje = self.score_llamada
            elif (
                self.nivel_llamada == "MEDIO"
                and self.score_llamada < self.bajada_medio
                and tiempo_en_nivel >= self.permanencia_medio_seg
            ):
                self.nivel_llamada = "BAJO"
                self.t_nivel_desde = ahora
                self.recomendacion = recomendacion_para("BAJO")
                self.mensaje_alerta = _MENSAJES_POR_NIVEL["BAJO"]
                self._score_mensaje = self.score_llamada

        # d) Actualizar score_max, nivel_max e indicadores
        score_redondeado = int(round(self.score_llamada))
        if score_redondeado > self.score_max:
            self.score_max = score_redondeado
        if _ORDEN_NIVEL[self.nivel_llamada] > _ORDEN_NIVEL[self.nivel_max]:
            self.nivel_max = self.nivel_llamada

        candidatos_ind: list[str] = []
        if hallazgos:
            candidatos_ind.extend(h for h in hallazgos if isinstance(h, str))
        if nivel_frag != "BAJO" and msg_frag:
            candidatos_ind.append(msg_frag)
        for ind in candidatos_ind:
            ind_limpio = ind.strip()
            if (
                ind_limpio
                and ind_limpio != _MENSAJES_POR_NIVEL["BAJO"]
                and ind_limpio not in self.indicadores
            ):
                self.indicadores.append(ind_limpio)

        # e) Devolver estado público + subio_nivel
        return {
            "nivel_riesgo": self.nivel_llamada,
            "score": score_redondeado,
            "score_llamada": self.score_llamada,
            "nivel_llamada": self.nivel_llamada,
            "mensaje_alerta": self.mensaje_alerta,
            "recomendacion": self.recomendacion,
            "score_max": self.score_max,
            "nivel_max": self.nivel_max,
            "indicadores": list(self.indicadores),
            "subio_nivel": subio_nivel,
        }

    def limpiar(self) -> None:
        self.historial.clear()
