# VishGuard Backend — Arquitectura tras la modularización

Este documento describe qué hace cada carpeta y cada archivo después de separar la lógica que antes vivía toda en `main.py`. Sirve como mapa de referencia para cualquier persona del equipo que necesite ubicar dónde vive cada responsabilidad.

---

## Vista general de la estructura

```
vishguard-backend/
├── main.py
├── database.py
├── core/
│   ├── __init__.py
│   └── connection_manager.py
├── services/
│   ├── __init__.py
│   └── heuristic_engine.py
├── modules/
│   ├── __init__.py
│   └── analyzer.py
└── api/
    ├── __init__.py
    └── routes/
        ├── __init__.py
        ├── health.py
        ├── alerts.py
        ├── stream.py
        └── analysis.py
```

---

## `main.py`

Punto de entrada de la aplicación. Ya no contiene lógica de negocio ni endpoints directamente definidos. Sus únicas responsabilidades son:

- Llamar a `init_db()` para asegurar que la base de datos exista.
- Crear la instancia de `FastAPI`.
- Registrar el middleware de CORS.
- Incluir los routers definidos en `api/routes/` (`health`, `alerts`, `stream`, `analysis`).
- Levantar el servidor con `uvicorn` cuando se ejecuta como script (`python main.py`).

Si se necesita agregar un endpoint nuevo, **no se edita este archivo salvo para una línea de `include_router`** — el endpoint en sí se crea en `api/routes/`.

---

## `database.py`

Sin cambios respecto al original. Contiene `init_db()`, `SessionLocal` y el modelo `AlertHistory`. Todos los módulos que necesitan leer o escribir alertas lo importan desde aquí (actualmente `api/routes/alerts.py` y `api/routes/stream.py`).

---

## `core/`

Piezas de infraestructura reutilizables que **no son endpoints ni lógica de negocio de detección**. No deben depender de `app` ni tener decoradores de ruta.

### `core/connection_manager.py`
Define la clase `ConnectionManager`, encargada de:
- Aceptar y registrar conexiones WebSocket activas.
- Desconectar clientes.
- Hacer broadcast a todos los clientes conectados (uso previsto para notificaciones masivas, aunque el flujo actual de `/ws/stream` responde directo al cliente en vez de hacer broadcast).

La *instancia* de esta clase (`manager = ConnectionManager()`) se crea en `api/routes/stream.py`, no aquí — este archivo solo aporta la definición.

*(A futuro, aquí también vivirán `config.py`, `db.py` y `security.py` del módulo de autenticación JWT que se está integrando desde el template de FastAPI.)*

---

## `services/`

Lógica de negocio pura, sin ninguna dependencia de FastAPI. Debe poder importarse y probarse (`pytest`) sin necesidad de levantar un servidor.

### `services/heuristic_engine.py`
Contiene el motor de detección basado en reglas:
- Las listas de patrones regex por categoría: `PATRONES_CRITICOS_FRAUDE`, `PATRONES_COACCION_URGENCIA`, `PATRONES_INSTITUCIONES`, `PATRONES_COMERCIAL`, `PATRONES_SEGUROS`.
- `evaluar_amenaza(texto)`: aplica los patrones, calcula el score y devuelve `(nivel, score, recomendación, hallazgos)`.
- `evaluar_amenaza_como_json(texto)`: adapta esa salida al mismo formato JSON (`nivel_riesgo`, `score`, `patrones_detectados`, `frase_critica`, `recomendacion`) que produce el análisis por LLM, para que ambos caminos sean intercambiables.

Este es el motor que actúa como **respaldo local** cuando el LLM (Groq) no está disponible o falla.

---

## `modules/`

### `modules/analyzer.py`
Define la clase `VishingAnalyzer`, el punto de entrada único de análisis usado tanto por el WebSocket como por el endpoint REST:
- Si hay `GROQ_API_KEY` configurada, intenta clasificar el texto con el modelo Llama 3.3 vía Groq, pidiendo una respuesta en JSON estructurado.
- Si no hay API key, o si la llamada a Groq falla, cae automáticamente en `evaluar_amenaza_como_json()` de `services/heuristic_engine.py` como respaldo — en vez del stub fijo que existía antes.

Esta es la clase que centraliza la decisión de "¿usamos IA o heurística?", para que ningún endpoint tenga que preocuparse por esa lógica.

---

## `api/routes/`

Aquí viven exclusivamente los endpoints (routers de FastAPI). Cada archivo expone un `router = APIRouter()` que luego `main.py` incluye con `include_router()`.

### `api/routes/health.py`
- `GET /` — chequeo de salud simple, devuelve el estado del sistema. Útil para monitoreo/uptime.

### `api/routes/alerts.py`
- `GET /alerts` — consulta el historial de alertas guardadas en `AlertHistory`, ordenadas por fecha descendente. Usa `database.SessionLocal` directamente.

### `api/routes/stream.py`
- Define el `ConnectionManager` (instancia) y la clase `VishingAnalyzer` (instancia) usados por el canal en vivo.
- `WS /ws/stream` — recibe texto transcrito en tiempo real, lo pasa a `VishingAnalyzer.analizar_texto()`, guarda en base de datos si el riesgo es `PELIGROSO`/`FRAUDE`/`MEDIO`, y responde al mismo cliente con el JSON de evaluación.
- Es el archivo más "orquestador": conecta el motor de análisis con la persistencia y el transporte WebSocket, pero delega el trabajo pesado a `modules/analyzer.py` y `database.py`.

### `api/routes/analysis.py`
- Define el modelo `CallRequest` (pydantic) usado como body del endpoint.
- `POST /analizar-llamada` — recibe un texto completo (no en streaming), lo evalúa y devuelve `nivel_riesgo`, `score` y `recomendacion`.

*(A futuro, aquí también vivirán `login.py` y `users.py` del módulo de autenticación.)*

---

## Cómo decidir dónde poner algo nuevo

Como regla rápida para el equipo:

| Si vas a agregar... | Va en... |
|---|---|
| Un endpoint HTTP o WebSocket nuevo | `api/routes/` (archivo nuevo o existente según el dominio) |
| Una regla de detección o cambio de score | `services/heuristic_engine.py` |
| Un cambio en cómo se decide LLM vs heurístico | `modules/analyzer.py` |
| Infraestructura reutilizable sin lógica de negocio (managers, config, seguridad) | `core/` |
| Un modelo de base de datos nuevo | `database.py` |
| Un modelo de entrada/salida (pydantic) específico de un endpoint | junto al router que lo usa en `api/routes/`, o en un futuro `schemas/` si crecen mucho |

Si un cambio "no encaja claramente" en ninguna fila de esta tabla, es una señal de que probablemente se está mezclando responsabilidades — vale la pena pausar y decidir antes de escribir el código, en vez de meterlo donde sea más rápido.
