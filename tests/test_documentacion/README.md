# Suite de Pruebas Automatizadas VishGuard AI (pytest)

Esta suite de pruebas está estructurada conforme al **Plan de Pruebas Automatizadas — Backend VishGuard AI** (`plan_pruebas_automatizadas_vishguard.xlsx`).

## Estructura de la Suite

| No. | Archivo | Función / Módulo |
|---|---|---|
| 1 | `test_01_stt.py` | Transcripción de audio (STT) |
| 2 | `test_02_pcm_wav.py` | Conversión PCM → WAV |
| 3 | `test_03_ws_audio.py` | Canal WebSocket de audio (/ws/stream) |
| 4 | `test_04_twilio_streaming.py` | Streaming Twilio (/twilio/voice y /ws/twilio) |
| 5 | `test_05_ia_analyzer.py` | Analizador de fraude (IA Gemini Flash) |
| 6 | `test_06_heuristic_engine.py` | Motor heurístico (respaldo local) |
| 7 | `test_07_ia_fallback.py` | Respaldo ante fallo de la IA (Resiliencia) |
| 8 | `test_08_pii_sanitization.py` | Sanitización de PII |
| 9 | `test_09_volatile_buffer.py` | Buffer de audio volátil |
| 10 | `test_10_auth_jwt.py` | Registro e inicio de sesión (JWT) |
| 11 | `test_11_users_permissions.py` | Usuarios y permisos |
| 12 | `test_12_alerts_history.py` | Historial de alertas |
| 13 | `test_13_endpoints_health_analysis.py` | Endpoints de análisis y salud |
| 14 | `test_14_pipeline_completo.py` | Pipeline completo (E2E) |

## Ejecución

Para ejecutar todas las pruebas:
```bash
pytest -v
```

Para ejecutar un módulo específico:
```bash
pytest -v test_08_pii_sanitization.py
```
