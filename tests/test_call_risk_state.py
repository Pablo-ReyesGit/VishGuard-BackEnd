import time

import pytest

import core.call_risk_state as crs
from core.call_risk_state import EstadoRiesgoLlamada
from modules.resilience.heuristic_engine import HeuristicEngine, _PETICION
from modules.resilience.resilience_manager import build_user_prompt


class RelojControlado:
    def __init__(self, inicial: float = 0.0) -> None:
        self.t = float(inicial)

    def __call__(self) -> float:
        return self.t

    def avanzar(self, segundos: float) -> float:
        self.t += float(segundos)
        return self.t


def test_secuencia_5_85_5_mantiene_peligroso(monkeypatch):
    reloj = RelojControlado(100.0)
    monkeypatch.setattr(time, "monotonic", reloj)

    estado = EstadoRiesgoLlamada(call_id="CA_TEST_1")

    r1 = estado.actualizar(5, "BAJO", "Sin indicadores de riesgo", "Segura")
    assert r1["nivel_riesgo"] == "BAJO"
    assert r1["subio_nivel"] is False

    reloj.avanzar(3.0)
    r2 = estado.actualizar(
        85,
        "PELIGROSO",
        "Solicitud explícita de tarjeta, PIN, CVV o código SMS.",
        "Cuelgue de inmediato.",
    )
    assert r2["nivel_riesgo"] == "PELIGROSO"
    assert r2["score"] == 85
    assert r2["subio_nivel"] is True

    reloj.avanzar(3.0)
    r3 = estado.actualizar(5, "BAJO", "Sin indicadores de riesgo", "Segura")
    assert r3["nivel_riesgo"] == "PELIGROSO"
    assert r3["score"] == 82  # 85 - 3 s * 1.0 pt/s
    assert r3["score_max"] == 85
    assert r3["nivel_max"] == "PELIGROSO"
    assert r3["subio_nivel"] is False


def test_bajada_desde_peligroso_a_medio_y_nunca_salta_a_bajo_en_un_paso(monkeypatch):
    reloj = RelojControlado(0.0)
    monkeypatch.setattr(time, "monotonic", reloj)

    estado = EstadoRiesgoLlamada(call_id="CA_TEST_2")
    estado.actualizar(85, "PELIGROSO", "Solicitud de PIN", "Cuelgue")
    assert estado.nivel_llamada == "PELIGROSO"

    niveles_vistos = [estado.nivel_llamada]
    # Fragmentos de score 0 cada 3 s:
    # Con score inicial 85 y decaimiento 1 pt/s, a los 21 s el score es 64 (>= 50, sigue PELIGROSO).
    # Recién a los 36 s (12 pasos de 3 s) el score baja a 49 (< 50) y permanencia 36 s >= 20 s -> MEDIO.
    for paso in range(1, 12):
        reloj.avanzar(3.0)
        res = estado.actualizar(0, "BAJO")
        assert res["nivel_riesgo"] == "PELIGROSO", f"Bajó antes de tiempo en paso {paso} (t={reloj.t}s)"
        niveles_vistos.append(res["nivel_riesgo"])

    # Paso 12 (t = 36 s): score = 49 < 50 y tiempo en PELIGROSO = 36 s >= 20 s -> baja a MEDIO
    reloj.avanzar(3.0)
    res_medio = estado.actualizar(0, "BAJO")
    assert res_medio["nivel_riesgo"] == "MEDIO"
    assert res_medio["score"] == 49
    niveles_vistos.append(res_medio["nivel_riesgo"])

    # Incluso si pasaran 100 s de golpe desde PELIGROSO, nunca salta directo de PELIGROSO a BAJO
    reloj2 = RelojControlado(0.0)
    estado_salto = EstadoRiesgoLlamada(call_id="CA_SALTO", clock=reloj2)
    estado_salto.actualizar(85, "PELIGROSO", "Alerta crítica", "Cuelgue")
    reloj2.avanzar(100.0)
    r_un_escalon = estado_salto.actualizar(0, "BAJO")
    assert r_un_escalon["nivel_riesgo"] == "MEDIO"
    reloj2.avanzar(10.0)
    r_segundo_escalon = estado_salto.actualizar(0, "BAJO")
    assert r_segundo_escalon["nivel_riesgo"] == "BAJO"


def test_secuencia_5_50_5_queda_en_medio_y_no_baja_antes_de_10s(monkeypatch):
    reloj = RelojControlado(50.0)
    monkeypatch.setattr(time, "monotonic", reloj)

    estado = EstadoRiesgoLlamada(call_id="CA_TEST_3")

    r1 = estado.actualizar(5, "BAJO")
    assert r1["nivel_riesgo"] == "BAJO"

    reloj.avanzar(3.0)
    r2 = estado.actualizar(50, "MEDIO", "Presión detectada", "Precaución")
    assert r2["nivel_riesgo"] == "MEDIO"
    assert r2["subio_nivel"] is True

    reloj.avanzar(3.0)
    r3 = estado.actualizar(5, "BAJO")
    assert r3["nivel_riesgo"] == "MEDIO"
    assert r3["score"] == 47

    # Incluso si el score cayera bajo 25 antes de cumplir los 10 s de permanencia en MEDIO,
    # no debe bajar a BAJO antes de 10 s.
    reloj_rapido = RelojControlado(0.0)
    estado_corto = EstadoRiesgoLlamada(clock=reloj_rapido)
    estado_corto.decaimiento_pts_seg = 5.0  # decae rápido para probar tope de permanencia de 10 s
    estado_corto.actualizar(42, "MEDIO", "Motivo de alerta", "No comparta datos")
    reloj_rapido.avanzar(6.0)  # 6 s < 10 s, aunque score_llamada = 42 - 30 = 12 < 25
    r_antes = estado_corto.actualizar(0, "BAJO")
    assert r_antes["nivel_riesgo"] == "MEDIO"

    reloj_rapido.avanzar(4.0)  # total 10 s en MEDIO y score < 25 -> ahora sí baja a BAJO
    r_despues = estado_corto.actualizar(0, "BAJO")
    assert r_despues["nivel_riesgo"] == "BAJO"


def test_contexto_y_regex_peticion():
    reloj = RelojControlado(0.0)
    estado = EstadoRiesgoLlamada(clock=reloj)
    estado.agregar_contexto("llamante", "Hola le hablo del banco")
    reloj.avanzar(2.0)
    estado.agregar_contexto("receptor", "Sí dígame")
    ctx = estado.texto_contexto()
    assert ctx == "Llamante: Hola le hablo del banco\nReceptor: Sí dígame"

    prompt = build_user_prompt("deme su clave", ctx)
    assert "Historial reciente de la llamada (puede estar vacío):" in prompt
    assert "Fragmento NUEVO a evaluar:" in prompt

    heur = HeuristicEngine()
    for frase in ("dame tu pin", "deme su clave", "déme el código"):
        ev = heur.evaluate(frase)
        assert ev["nivel_riesgo"] == "PELIGROSO", frase
        assert ev["score"] >= 85, frase

    frase_inocente = "me da miedo que me clonen la tarjeta"
    assert _PETICION.search(frase_inocente) is None
    assert heur.evaluate(frase_inocente)["nivel_riesgo"] == "BAJO"
