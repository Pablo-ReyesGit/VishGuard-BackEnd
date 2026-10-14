# VishGuard Backend — Registro de cambios y deuda técnica

Documento de referencia sobre la refactorización de `main.py` (monolito) hacia una arquitectura modular basada en routers de FastAPI. Su objetivo es dejar constancia de **qué se cambió, qué problemas existían, cuáles se corrigieron y cuáles siguen abiertos**, para que el equipo no vuelva a introducir la misma deuda técnica.

---

## 1. Motivación del cambio

`main.py` concentraba, en un solo archivo:

- Configuración y arranque de la app (FastAPI, CORS)
- Gestión de conexiones WebSocket (`ConnectionManager`)
- Dos endpoints REST (`/`, `/alerts`)
- El endpoint WebSocket (`/ws/stream`)
- Un motor heurístico completo (patrones regex + función de scoring)
- El modelo Pydantic de entrada (`CallRequest`)
- Lógica de persistencia en base de datos

Esto hacía que cualquier cambio pequeño (ajustar un patrón, agregar un endpoint) implicara tocar un archivo de cientos de líneas con responsabilidades mezcladas, y dificultaba las pruebas unitarias porque todo dependía de que `app` estuviera instanciado.

---

## 2. Problema funcional más importante detectado: dos motores de detección desincronizados

Antes de tocar la estructura de carpetas, se detectó un **bug de diseño, no solo de organización**:

- El canal WebSocket (`/ws/stream`) usaba `VishingAnalyzer.analizar_texto()` (LLM vía Groq).
- El canal REST (`/analizar-llamada`) usaba una función local `evaluar_amenaza()` con sus propios umbrales (75/40), definida directamente en `main.py`.
- Los umbrales de `evaluar_amenaza()` **no coincidían** con los documentados en los diagramas PlantUML del proyecto (70/40/20 para ROJO/NARANJA/AMARILLO/VERDE).
- El fallback de `VishingAnalyzer` (`_evaluacion_local`) era un **stub fijo**: devolvía siempre `"MEDIO", score 50`, sin importar el contenido real de la llamada — contradiciendo el diseño documentado de *Resilience Manager* con circuit breaker que debía caer a un motor heurístico real ante fallos del LLM.

### Corrección aplicada
Se conectó el motor heurístico (`evaluar_amenaza` / `evaluar_amenaza_como_json`) como el **fallback real** de `VishingAnalyzer`, de modo que:
- Ambos canales (WS y REST) llaman al mismo punto de entrada de análisis.
- Cuando falla o no está disponible el LLM, la respuesta sigue siendo una evaluación basada en las reglas calibradas del proyecto, no un valor genérico.

### Pendiente de decisión (no resuelto todavía)
Los diagramas PlantUML mencionan **Gemini Flash** como servicio externo del circuit breaker, pero el código implementado usa **Groq / Llama 3.3**. Hay que decidir y documentar si:
- Se actualiza el diagrama para reflejar Groq, o
- Se planea usar ambos proveedores (p. ej. Gemini como segundo fallback antes del heurístico).

Dejar esta discrepancia sin resolver es deuda técnica de documentación: alguien del equipo que solo lea el diagrama va a esperar un comportamiento que el código no tiene.

---

## 3. Inconsistencia de persistencia

- El canal WebSocket guarda en `AlertHistory` cuando el nivel de riesgo es `PELIGROSO`, `FRAUDE` o `MEDIO`.
- El endpoint REST `/analizar-llamada` **no persistía nada** en el `main.py` original.

**Riesgo si no se corrige:** el historial de `/alerts` quedaría incompleto según el canal por el que entró la llamada, lo cual puede confundir al equipo o a un futuro dashboard que consuma `/alerts`. Queda como pendiente decidir si el REST también debe persistir (probablemente sí, por consistencia).

---

## 4. Errores de ejecución durante la migración (y su causa raíz)

Estos errores no fueron culpa de la arquitectura en sí, sino de cómo se movió el código durante la migración. Se documentan porque son el tipo de error que se repite si el patrón no queda claro para todo el equipo:

| Error visto | Causa raíz | Lección |
|---|---|---|
| `ImportError: cannot import name 'evaluar_amenaza_como_json'` | La función adaptadora no se creó (o no se guardó) en `services/heuristic_engine.py` | Al mover lógica, verificar que el *nombre exacto* importado exista en el archivo destino |
| `NameError: name 'app' is not defined` en `heuristic_engine.py` | Se copió el endpoint completo (`@app.post(...)`) dentro de un archivo de servicio puro | Los módulos en `services/` y `core/` **nunca** deben depender de la instancia `app` ni tener decoradores de ruta — esa lógica pertenece solo a `api/routes/` |
| `cannot import name 'ConnectionManager'` (sugería `connection_manager`) | Mezcla entre la definición de la clase y la instancia dentro del mismo archivo | Cada archivo de `core/` define la clase; la instancia se crea donde se usa (`api/routes/stream.py`) |
| `cannot import name 'alerts' from 'api.routes'` / `cannot import name 'analysis' from 'api.routes'` | Los archivos `alerts.py` y `analysis.py` no existían aún (o estaban vacíos/mal nombrados) en el momento de actualizar `main.py` | Al fraccionar un monolito, crear **todos** los archivos de destino antes de actualizar los imports centrales, o hacerlo incrementalmente probando cada import por separado |

**Recomendación a futuro:** cuando se divida un archivo grande, mover una responsabilidad a la vez y correr el servidor después de cada movimiento, en vez de mover todo y luego intentar arrancar. Habría evitado la cadena de 5-6 reinicios fallidos vista en este proceso.

---

## 5. Otras mejoras identificadas, aún no aplicadas (deuda técnica pendiente)

Estas no bloqueaban la compilación, así que quedaron fuera del alcance inmediato, pero deberían registrarse como tareas futuras:

1. **Logging real en vez de `print()`**: reemplazar los `print("📥 ...")`, `print("💾 ...")`, etc. por `logging.getLogger(__name__)` con niveles (`info`, `warning`, `error`). Esto permite filtrar ruido en producción y no depende de que la consola soporte emojis.
2. **`__init__.py` en los paquetes nuevos**: confirmar que `core/`, `services/`, `api/` y `api/routes/` tengan `__init__.py` (aunque esté vacío). En Python 3.13 sobre Windows, su ausencia puede producir mensajes de import confusos como `(unknown location)`.
3. **Timeout explícito hacia Groq**: agregar un timeout (p. ej. 2.5s, como documentan los diagramas del circuit breaker) a la llamada `self.client.chat.completions.create(...)`, ya que actualmente no hay uno explícito y una respuesta lenta del LLM podría bloquear la request más de lo esperado.
4. **Persistencia consistente**: decidir si `/analizar-llamada` debe guardar en `AlertHistory` igual que el WebSocket (ver punto 3 de este documento).
5. **Integración con el módulo de autenticación JWT**: al estar incorporando `core/security.py`, `api/deps.py`, `api/routes/login.py` y `api/routes/users.py` desde el template `fastapi/full-stack-fastapi-template`, definir explícitamente qué rutas quedan públicas (por ejemplo `/` de salud) y cuáles requieren `Depends(get_current_user)` — antes de que crezca más el número de endpoints y se vuelva ambiguo.
6. **Pruebas unitarias del motor heurístico**: ahora que `evaluar_amenaza()` vive en un módulo aislado sin dependencias de FastAPI, es el momento ideal de agregar tests (`pytest`) que verifiquen los patrones críticos, antes de que el archivo crezca más y sea más difícil de cubrir.

---

## 6. Resumen

La refactorización resolvió el problema estructural principal (monolito en `main.py`) y, en el camino, destapó un bug funcional real (motor de fallback que ignoraba el contenido de la llamada). Los errores de importación vistos durante el proceso fueron efectos esperables de mover código entre archivos y ya están resueltos. Lo que queda pendiente (sección 5) no es urgente para que el sistema funcione, pero si se posterga demasiado tiempo se convierte en la misma clase de deuda técnica que motivó este cambio.
