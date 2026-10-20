# Sprint 1 y 2 - v2 (tras auditoría)

Estructura (la carpeta se llama `modules/Security`, con S mayúscula, igual que en tus imports):
core/{log_sanitizer,passwords,config_security}.py
modules/Security/{pii_sanitizer,volatile_buffer,rate_limit}.py
modules/resilience/{heuristic_engine,resilience_manager,audio_frame_guard}.py
tests/test_privacidad_logs_memoria_y_config.py   (Sprint 1, 37 pruebas)
tests/test_resiliencia_heuristica_e_ingesta.py   (Sprint 2, 49 pruebas)
tests/test_integracion_analizador_y_canal_ws.py  (integración, 17 pruebas)
services/analyzer.py        -> reemplaza tu analyzer.py (VishingAnalyzer, misma clase)
api/routes/stream.py        -> reemplaza tu stream.py (/ws/stream)

IMPORTANTE (Windows): Python distingue mayúsculas en los nombres de módulo aunque el disco no.
Usa SIEMPRE `modules.Security` (nunca `modules.security`); mezclar ambos duplica las clases y
una excepción como SanitizationError deja de capturarse.

Ejecutar: `pip install -r requirements-sprint12.txt` y `pytest tests -v`
(requiere tu `services/heuristic_engine.py` real).

## Integración
1. main.py (startup): `install_log_sanitizer()`; `FastAPI(docs_url=settings.docs_url, redoc_url=settings.docs_url)`.
2. Analizador: `await resilience.analizar(texto)` con una instancia global
   `ResilienceManager(gemini_llm_call(GEMINI_API_KEY, modelos))` (el breaker debe compartirse).
3. Stream Twilio: `guard.validate_stream_format(start["mediaFormat"])`; por cada `media`
   `guard.inspect(payload)` -> `buffer.append(v.payload)`; `buffer.close()` al terminar.
   Usar un buffer por pista (inbound/outbound) si necesitas identificar quién habla.
4. /login: `limiter.allow(client_key(request.headers, request.client.host, trust_forwarded=<solo si el proxy es de confianza>))`.
   WS: `with conn_limiter.hold(user_id): ...` (captura TooManyConnections y cierra con 1008).
5. Contraseñas: usar core/passwords.py (argon2). En /login, verificar contra un hash ficticio si el usuario no existe.
6. Prohibido loguear transcripciones en INFO; reemplazar los print() del analizador por logging.
7. Decisión de diseño pendiente de tu aprobación: una mención aislada de dato sensible pesa 30
   (BAJO); solo pesa 85 si es una petición explícita o hay otra categoría corroborando
   (PUNTOS_CRITICO_AISLADO en heuristic_engine.py).

## Dónde va cada archivo
modules/analyzer.py              -> reemplaza tu modules/analyzer.py (VishingAnalyzer, misma clase)
api/routes/stream.py             -> reemplaza tu stream.py (/ws/stream, canal de alertas a la app)
api/routes/twilio_stream.py      -> reemplaza tu archivo de Twilio (cambios marcados con "[S1-2]"; haz diff contra el tuyo)
modules/resilience/call_session.py -> NUEVO: políticas de ingesta por llamada (buffers, guard, límites)
core/log_sanitizer.py            -> reemplaza (ahora también enmascara ?numero=, ?telefono=, ?phone=)
tests/test_integracion_*.py      -> pruebas de integración (analizador/canal WS y ruta de Twilio)

## Qué cambió en la ruta de Twilio (todo marcado con [S1-2])
- AudioFrameGuard (uno por pista): formato mu-law 8 kHz (si Twilio informa mediaFormat), base64, tamaño de trama, VAD.
- VolatileAudioBuffer por pista (reemplaza el bytearray): límite de sesión y borrado a cero al cerrar la llamada.
- Límites: llamadas simultáneas (1013), ritmo de tramas y tramas inválidas (1008), evento JSON enorme (1009),
  formato no soportado (1003), inactividad, duración máxima por pista, contrapresión de análisis pendientes.
- Un bloque sin ninguna trama con voz no gasta STT ni IA (con VISHGUARD_STT=simulado se conserva el comportamiento original).
- La alerta (WebSocket a la app + DB) sale con el texto SANITIZADO (sin tarjetas, correos, teléfonos, PINs); el análisis usa el original.
- JSON válido pero no-dict, customParameters/media/track con tipos raros: ya no tumban la llamada.
- GrabadorWav: purga por TTL (VISHGUARD_WAV_TTL_HORAS, 24 h) de los .wav viejos (T3).
- _etapa_analisis NO cambió (sigue usando analyzer.analizar_texto en un hilo): compatible con tus pruebas que lo simulan.

## Variables nuevas
VISHGUARD_WAV_TTL_HORAS=24  VISHGUARD_MAX_LLAMADAS=20  VISHGUARD_MAX_FRAME_BYTES=4096  VISHGUARD_MAX_SEG_PISTA=7200
VISHGUARD_MAX_PENDIENTES=5  VISHGUARD_MAX_FRAMES_VENTANA=1500  VISHGUARD_WS_MAX_MENSAJE=65536  VISHGUARD_WS_IDLE_SEG=60
WS_TRUST_FORWARDED, WS_MAX_MSG_CHARS, WS_MAX_CONN_POR_USUARIO, WS_MSG_POR_VENTANA (canal /ws/stream)

## Si tu suite existente (tests/twillo_vishing_test.py) falla tras el cambio, revisa primero:
1. Pruebas que envían UNA trama grande (p. ej. 24 000 bytes mu-law = 3 s): superan VISHGUARD_MAX_FRAME_BYTES.
   Twilio real envía 160 bytes por trama. Sube la variable en esa prueba o parte la trama.
2. Pruebas que comparan `texto` de la alerta con un texto que contenga números/correos: ahora sale sanitizado.
3. Pruebas que envían decenas de tramas inválidas o miles de tramas por segundo.

## Pendiente (Sprint 3, no se tocó para no romper tu flujo actual)
- /ws/twilio NO tiene autenticación: cualquiera puede conectarse, declarar `to` de otra persona y generar
  alertas falsas en su app y en la DB (y consumir cuota de Gemini). Solución prevista (T5): ticket de un solo
  uso (<Parameter name="ticket">) emitido en el webhook y verificado en el evento `start`.
- _validar_firma_twilio sigue siendo fail-open si no hay TWILIO_AUTH_TOKEN.
- VISHGUARD_LOG_TEXTO imprime transcripciones a nivel INFO (el documento lo prohíbe); sigue apagado por defecto.
- core.alert_service.guardar_alerta_si_aplica: el analizador ahora devuelve solo nivel_riesgo, score,
  mensaje_alerta y recomendacion (+ hablante, texto, inicio_ms). Verifica que no lea patrones_detectados/frase_critica.

## Diagnóstico de Gemini (llamada de prueba del 2026-10-11: 400 en los 3 modelos)
Ejecuta `python diagnostico_gemini.py`: indica si la CLAVE es válida, si los modelos EXISTEN para esa clave y
si una llamada mínima (como la del analizador original) funciona. El adaptador ahora registra
`ClientError <código> <estado>: <mensaje saneado>` en vez de solo `ClientError`.
Cambios del adaptador: sin http_options.timeout por petición (el SDK lo enviaba como cabecera X-Server-Timeout),
timeout a nivel de cliente httpx, y AFC desactivado (desaparece el aviso "AFC is enabled" en cada llamada).
Recomendado: precargar Whisper al arrancar (`await asyncio.to_thread(twilio_stream.precargar_stt)` en el lifespan).

- GEMINI_MAX_TOKENS (defecto 500): tope de tokens de salida. Los modelos con razonamiento gastan parte "pensando"; si diagnostico_gemini.py
  muestra finish=MAX_TOKENS o JSON TRUNCADO, súbelo (p. ej. 1024).
- core/log_sanitizer ahora enmascara las claves de Google con formato nuevo "AQ.…".
