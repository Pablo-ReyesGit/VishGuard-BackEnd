"""Fallback de patrones SOLO para que el paquete preliminar sea testeable aislado.
Si el backend real incluye services.heuristic_engine, se usa ese módulo sin sustituirlo.
"""
import importlib.util
import sys
import types
import re

try:
    _has_real_engine = importlib.util.find_spec("services.heuristic_engine") is not None
except ModuleNotFoundError:
    _has_real_engine = False

if not _has_real_engine:
    services = types.ModuleType("services")
    services.__path__ = []
    engine = types.ModuleType("services.heuristic_engine")
    engine.PATRONES_CRITICOS_FRAUDE = [r"\b(pin|nip|cvv|código sms|token)\b", r"dígame su pin", r"dame tu clave"]
    engine.PATRONES_COACCION_URGENCIA = [r"cuenta suspendida", r"bloqueada", r"urgente", r"cargos no reconocidos"]
    engine.PATRONES_INSTITUCIONES = [r"\b(banco|bbva|soporte técnico)\b"]
    engine.PATRONES_COMERCIAL = [r"ganaste un premio", r"oferta exclusiva"]
    engine.PATRONES_SEGUROS = [r"hola mamá", r"ya voy para la casa", r"buenos días"]
    sys.modules.setdefault("services", services)
    sys.modules["services.heuristic_engine"] = engine
