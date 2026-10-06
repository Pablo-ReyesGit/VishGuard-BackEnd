# Guía de pruebas manuales: integración Twilio de VishGuard

Verificada el 4 de octubre de 2026 contra la documentación oficial de Twilio y probada con un backend real (uvicorn) y el simulador incluido.

## 0. Lo primero que debes saber

**En una cuenta Trial de Twilio, `<Stream>` y `<Dial><Number>` están bloqueados.** Según la página oficial *Try out Voice → Blocked verbs*, Twilio los elimina del TwiML y los reemplaza por un `<Say>` que dice "The {verb} verb is not available on trial accounts". Tu flujo usa exactamente esos dos, así que:

- **Fases 1 a 3 (gratis, locales):** funcionan sin Twilio y validan casi todo tu código.
- **Llamada real de extremo a extremo (Fase 5):** requiere **hacer upgrade** de la cuenta (el upgrade quita la restricción de números verificados y habilita TwiML personalizado completo).
- **Con la cuenta Trial todavía puedes comprobar algo útil:** que Twilio llega a tu webhook y que la firma se valida. Si al llamar oyes el aviso de verbo no disponible, es que tu servidor respondió TwiML válido.

Otros límites del Trial que conviene conocer: dura 30 días, incluye 75 minutos de voz, máximo 10 minutos por llamada, hasta 5 números verificados, las llamadas entrantes solo se aceptan desde números verificados (error 21264) y las llamadas están restringidas a tu país de registro (Guatemala está en la lista de países con Trial).

## Mapa de fases

| Fase | Qué valida | Costo | ¿Necesita Twilio? |
| --- | --- | --- | --- |
| 0 | Preparar entorno y variables | Gratis | No |
| 1 | Swagger: webhook, TwiML, debug | Gratis | No |
| 2 | Simulador: stream completo, alertas a la app | Gratis | No |
| 3 | ngrok: URL pública con HTTPS | Gratis | No |
| 4 | Cuenta, upgrade, número y webhook | Pago (upgrade) | Sí |
| 5 | Llamada real | Minutos de voz | Sí |
| 6 | Transcripción real con Groq y base de datos | API de Groq | Sí |

## Fase 0. Preparación

### Dependencias

```powershell
pip install python-multipart twilio audioop-lts websockets sqlmodel pyjwt
```

`audioop-lts` es necesario en Python 3.13, `python-multipart` lo usa `request.form()` y `websockets` el simulador.

### Activar los logs de VishGuard

Uvicorn solo muestra los logs de sus propios módulos. Sin esto **no verás** los mensajes `[VishGuard]` ni `Stream iniciado`. Pon esto al inicio de `main.py`, antes de crear `app`:

```python
import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
```

Comprueba también que `main.py` incluya los dos routers (`app.include_router(stream.router)` y `app.include_router(twilio_stream.router)`).

### Variables de entorno

No hay números ni claves escritos en el código: todo va por variables. Defínelas **en la misma ventana de PowerShell** donde arrancarás uvicorn. Los valores de un archivo `.env` no llegan a `os.getenv` salvo que tu proyecto cargue ese archivo.

```powershell
$env:VISHGUARD_DESTINO = "+502XXXXXXXX"      # tu celular real, formato E.164
$env:VISHGUARD_STT     = "simulado"          # luego "groq"
$env:VISHGUARD_DEBUG   = "1"                 # habilita /debug/connections
$env:PUBLIC_URL        = "http://127.0.0.1:8000"   # en Fase 3 será la URL https de ngrok
uvicorn main:app --host 0.0.0.0 --port 8000
```

| Variable | De dónde sale | Para qué |
| --- | --- | --- |
| `VISHGUARD_DESTINO` | Tu celular, con `+` y código de país | Número al que Twilio reenvía la llamada. Debe ser el mismo número con el que la app se registra en `/ws/stream` |
| `PUBLIC_URL` | URL https que te da ngrok, sin `/` final | Se usa para armar la URL `wss://` del stream y para validar la firma |
| `TWILIO_AUTH_TOKEN` | Consola de Twilio (Fase 4.2) | Valida que el webhook lo llame Twilio. **No lo definas en las Fases 1 y 2** |
| `VISHGUARD_STT` | `simulado` o `groq` | `simulado` envía un texto fijo y no guarda en la base de datos |
| `GROQ_API_KEY` | Tu cuenta de Groq | Solo con `groq` |
| `GROQ_STT_MODEL` | Opcional | Por defecto `whisper-large-v3-turbo` |
| `WS_AUTH_REQUIRED` | `true` para exigir JWT en `/ws/stream` | Opcional; la app debe enviar `?token=<JWT>` |
| `VISHGUARD_DEBUG` | `1` | Expone `/debug/connections` (números enmascarados) |
| `VISHGUARD_GUARDAR_WAV` | `1` para activar | Guarda el audio de cada llamada en un `.wav` (apagado por defecto) |
| `VISHGUARD_WAV_DIR` | Opcional | Carpeta de las grabaciones; por defecto `grabaciones`, relativa a la carpeta desde donde arrancas uvicorn |
| `VISHGUARD_WAV_MAX_SEG` | Opcional | Tope de segundos grabados por llamada y por hablante; por defecto 600 |
| `VISHGUARD_WAV_MODO` | `estereo` (defecto) o `mono` | `estereo`: canal izquierdo = llamante, derecho = receptor. `mono` mezcla a ambos en un solo canal |

## Fase 1. Pruebas con Swagger

Abre **http://127.0.0.1:8000/docs**. Swagger solo muestra rutas HTTP: **los WebSockets no aparecen** y se prueban en la Fase 2.

| # | Prueba | Cómo | Resultado esperado |
| --- | --- | --- | --- |
| 1 | Webhook devuelve TwiML | `POST /twilio/voice` → Try it out → Execute (sin cuerpo) | 200, `application/xml`, con `<Start><Stream ... url="ws://127.0.0.1:8000/ws/twilio">`, un `<Parameter name="to">` y `<Dial answerOnBridge="true"><Number>…` |
| 2 | Falta el destino | Cierra uvicorn, quita `VISHGUARD_DESTINO`, vuelve a arrancar y repite la prueba 1 | 500 "Destino no configurado" y sin `<Stream` en la respuesta |
| 3 | Firma exigida | Define `TWILIO_AUTH_TOKEN` y repite la prueba 1 | 403 "Firma de Twilio inválida". Es lo correcto: Swagger no firma las peticiones |
| 4 | Debug enmascarado | `GET /debug/connections` (con `VISHGUARD_DEBUG=1`) | `{"total":0,"conectados":[]}` y, con la app conectada, `["***8032"]` sin el número completo |
| 5 | Debug apagado | Quita `VISHGUARD_DEBUG` y repite | 404 |

Desde PowerShell puedes repetir la prueba 1 con `curl.exe -X POST http://127.0.0.1:8000/twilio/voice -d "CallSid=CA123&From=%2B50255551234"`.

## Fase 2. Simulador de Twilio y de la app

El archivo `tests/simular_twilio.py` hace de app Android (se conecta a `/ws/stream`) y de Twilio con **los dos lados de la llamada**: envía `connected`, `start` (con los parámetros `to` y `from`), frames `media` de la pista `inbound` (el llamante, un tono de 440 Hz) y de la pista `outbound` (el receptor, un tono de 880 Hz que empieza cuando "contesta"), y `stop`, todo a ritmo real y con `timestamp`. Con el backend corriendo y `VISHGUARD_STT=simulado`:

```powershell
python tests\simular_twilio.py --numero +502XXXXXXXX --segundos 8 --receptor-despues 1
```

Salida esperada, validada contra un servidor real:

```
[APP]    #1 LLAMANTE  @  0.0 s nivel=... score=...
[APP]    #2 RECEPTOR  @  1.0 s nivel=... score=...
[APP]    #3 LLAMANTE  @  3.0 s ...
[APP]    #4 RECEPTOR  @  4.0 s ...
[APP]    #5 LLAMANTE  @  6.0 s ...
[APP]    #6 RECEPTOR  @  7.0 s ...
RESUMEN: {'llamante': 3, 'receptor': 3}
RESULTADO: OK, la app recibió mensajes de llamante y receptor.
```

Salen 3 mensajes por hablante porque 8 s son dos bloques de 3 s más un remanente. Cada hablante se procesa por separado y el momento `@` es el instante de su primer frame, de modo que el receptor aparece a partir del segundo en que contestó. En la consola de uvicorn debe aparecer `Stream iniciado (callSid=CA_SIMULADO, llamante=***1234, receptor=***XXXX, pistas=['inbound', 'outbound'])`, un `[VishGuard] llamante ...` o `[VishGuard] receptor ...` por mensaje y `Transmisión finalizada por Twilio`.

Variantes útiles:

| Opción | Para qué sirve |
| --- | --- |
| `--receptor-despues 3` | El receptor contesta a los 3 s |
| `--solo-llamante` | Simula un stream de una sola pista (solo llega el llamante) |
| `--silencio` | Envía silencio en lugar de tonos |
| `--url wss://xxxx.ngrok-free.app` | Probar a través de ngrok |
| `--prefijo /api/v1` | Si incluyes los routers con prefijo |
| `--token <JWT>` | Si activas `WS_AUTH_REQUIRED` |

Con `VISHGUARD_STT=groq` los tonos no son voz y no se transcriben: para probar Groq usa una llamada real.

## Fase 3. URL pública con ngrok

Twilio solo se conecta a URLs públicas, y **`wss` es el único protocolo soportado para el stream**, por eso necesitas HTTPS.

1. Crea una cuenta en ngrok e instala el agente. Registra tu token una sola vez: `ngrok config add-authtoken <TU_TOKEN>`.
2. Con uvicorn corriendo en el 8000: `ngrok http 8000`. Si tienes un dominio fijo: `ngrok http 8000 --url https://<tu-dominio>.ngrok.dev`.
3. Copia la línea `Forwarding https://…` y úsala **sin barra final**:

```powershell
$env:PUBLIC_URL = "https://xxxx.ngrok-free.app"
```

Reinicia uvicorn para que lea la variable. Si usas el dominio temporal de ngrok, cambia en cada reinicio: tendrás que actualizar `PUBLIC_URL` y el webhook de Twilio.

Prueba: `POST https://xxxx.ngrok-free.app/twilio/voice` debe devolver ahora `wss://xxxx.ngrok-free.app/ws/twilio` en el TwiML. El inspector de ngrok en **http://127.0.0.1:4040** muestra cada petición que llega, con su respuesta.

## Fase 4. Consola de Twilio

Twilio tiene hoy dos variantes de consola: la nueva (`https://1console.twilio.com/`) y la **Legacy Console**. Su documentación describe ambas.

### 4.1 Cuenta y upgrade

1. Crea tu cuenta en [https://www.twilio.com/try-twilio](https://www.twilio.com/try-twilio) (verificas correo y tu teléfono, que queda como número verificado).
2. Para la llamada real con `<Stream>`, haz el upgrade: clic en el aviso **Trial** (arriba a la izquierda) o en **Upgrade your account**, o busca "Upgrade" en la barra de búsqueda de la consola. Revisa en esa pantalla el depósito mínimo vigente.
3. Tras el upgrade se quitan las restricciones de verificados y se habilita el TwiML completo, con unidades gratuitas de voz (75 minutos) y de Media Streams (30 unidades) según la tabla oficial.

### 4.2 Credenciales

- **Consola nueva:** **API keys and Auth tokens**, pestaña **Auth Tokens**. Ahí están el **Account SID** y el **Auth Token**.
- **Consola Legacy:** el panel principal (Account Dashboard) muestra el Account SID y el Auth Token.

Para VishGuard solo necesitas el **Auth Token principal** en `TWILIO_AUTH_TOKEN`. No uses el secreto de una API Key: la firma del webhook se calcula con el Auth Token. Trátalo como una contraseña; si lo expones, regénéralo.

### 4.3 Número de teléfono

- **Consola nueva:** **Numbers & senders** → **Set up a new phone number**. Twilio puede pedirte un *compliance profile* antes de vender el número.
- **Consola Legacy:** **Phone Numbers → Manage → Buy a number** ([https://console.twilio.com/us1/develop/phone-numbers/manage/search)](https://console.twilio.com/us1/develop/phone-numbers/manage/search%29). Elige uno con capacidad de **Voice**; los números de mensajería son los que exigen el compliance profile.

### 4.4 Configurar el webhook de voz

URL a pegar: `https://<tu-url-ngrok>/twilio/voice` (si incluyes el router con prefijo, agrégalo), método **HTTP POST**.

- **Consola Legacy:** **Phone Numbers → Manage → Active numbers** → clic en tu número → pestaña **Configure** → sección **Voice Configuration** → en **A call comes in** elige **Webhook** → pega la URL → método POST → **Save configuration**.
- **Consola nueva:** **Numbers & senders** → tu número → pestaña **Configuration details** → **Voice** → **Edit details** → opción **Webhook** → pega la URL. La documentación vigente detalla estos pasos solo para Messaging; el de Voice es análogo, pero los nombres exactos pueden variar.

### 4.5 Variables finales

```powershell
$env:TWILIO_AUTH_TOKEN = "<tu Auth Token>"
$env:PUBLIC_URL        = "https://xxxx.ngrok-free.app"
```

Reinicia uvicorn. Desde ahora el webhook rechaza cualquier petición sin firma válida de Twilio.

## Fase 5. Llamada real

Antes de llamar, comprueba que uvicorn y ngrok estén activos, que la app (o el simulador) esté conectada a `/ws/stream` con el mismo número que `VISHGUARD_DESTINO` y que `GET /debug/connections` lo muestre.

1. Llama a tu número de Twilio desde otro teléfono.
2. **Inspector de ngrok (4040):** debe aparecer `POST /twilio/voice` con respuesta 200.
3. **Tu celular** (el de `VISHGUARD_DESTINO`) suena; al contestar queda conectada la llamada.
4. **Consola de uvicorn:** `Stream iniciado (callSid=CA…, llamante=***XXXX, receptor=***XXXX, pistas=['inbound', 'outbound'])` y, cada \~3 s de audio de cada hablante, `[VishGuard] llamante …` o `[VishGuard] receptor …`.
5. **La app** recibe un mensaje por cada bloque analizado, con los campos `hablante` (`llamante` o `receptor`), `texto` (lo transcrito) e `inicio_ms` (milisegundos desde el inicio de la llamada, para ordenar la conversación).
6. Al colgar: `Transmisión finalizada por Twilio`.

Con `VISHGUARD_STT=simulado` llega un mensaje cada 3 s por hablante con el texto fijo, sin importar lo que se hable, y no se guarda en la base de datos. Si la llamada falla, abre los registros de llamadas y el depurador de Twilio (en la Legacy Console están bajo **Monitor → Logs**) y busca la llamada por su hora.

## Fase 5b. Verificar el audio de la conversación completa

Los logs prueban que llegan datos al ritmo correcto, pero no que sean voz. Para comprobarlo, activa la grabación **antes de arrancar uvicorn**:

```powershell
$env:VISHGUARD_GUARDAR_WAV = "1"
uvicorn main:app --host 0.0.0.0 --port 8000
```

Haz una llamada y, al colgar, busca el archivo en la carpeta `grabaciones\` (dentro de la carpeta desde la que ejecutaste uvicorn). El nombre es `<CallSid>_<fecha>_<hora>.wav`. En el log verás `Grabando la conversación en ...` al empezar y `Grabación guardada: ... (N s)` al terminar.

**Cómo está grabada la conversación:**

- **Quien llama va en el canal izquierdo y quien recibe en el derecho.** Es el formato de grabación de llamadas con un canal por persona: con parlantes oyes a los dos, y con audífonos cada voz sale por un oído. Para una mezcla en un solo canal usa `$env:VISHGUARD_WAV_MODO = "mono"`.
- **Los turnos están alineados en el tiempo.** Cada frame se coloca según su `timestamp`, así que si el receptor contesta 5 s después, su canal arranca con 5 s de silencio y no se desfasa de la conversación.
- **Formato:** PCM de 16 bits y 8 kHz. Cada canal es exactamente el audio que entra a `transcribir_audio` para ese hablante, por lo que es la muestra ideal para el equipo de Whisper (un canal = una persona, sin tener que separar voces).

**Qué comprobar al escucharlo:**

1. Se oye la voz de quien llama por un lado y la de quien contesta por el otro.
2. **Revisa el canal derecho antes de que contestes.** Según la documentación de Twilio, la pista `outbound` es el audio que Twilio genera hacia la llamada, e incluye el del tramo hijo del `<Dial>` (tu voz), pero también puede traer música en espera. Si oyes el tono de llamada en ese canal, tu transcriptor recibirá ese ruido y conviene filtrarlo.
3. Si un canal está en silencio total, mira el log: la línea `Stream iniciado` debe mostrar `pistas=['inbound', 'outbound']`. Si solo aparece `inbound`, Twilio no está enviando la pista del receptor.

**Detalles de seguridad:**

- **Las grabaciones contienen voz de personas.** Graba solo llamadas de prueba propias o con consentimiento, y borra los archivos al terminar.
- **Agrega `grabaciones/` a tu `.gitignore`** para no subirlas al repositorio.
- La grabación **nunca interrumpe la llamada**: si falla el disco o se llega al tope de duración, se detiene y deja un aviso en el log.
- El `timestamp` llega por un WebSocket sin autenticar, por lo que se comprueba el tope antes de rellenar silencios: un valor absurdo no puede reservar memoria.

### Contrato de entrega para Whisper

El equipo de Whisper solo tiene que sustituir el cuerpo de `transcribir_audio(pcm8k: bytes) -> str` en `twilio_stream.py`:

- **Entrada:** PCM de 16 bits, mono, 8 kHz, en bloques de 3 s (48,000 bytes) **de un solo hablante**. Cada hablante tiene su propio bloque, así que no hace falta separar voces. Con un canal del WAV grabado puedes simular esa entrada.
- **Conversión:** `_a_wav_16k(pcm8k)` ya devuelve el WAV a 16 kHz que Whisper espera.
- **Salida:** el texto transcrito. Si devuelve una cadena vacía, el bloque se descarta sin pasar al análisis.
- La función no recibe quién habla: el backend etiqueta el mensaje después, a partir de la pista de la que vino el audio.
- Esa función corre en un hilo aparte (`asyncio.to_thread`), así que puede bloquear sin frenar el audio. Los dos hablantes se procesan **en paralelo**.

### Mensaje que recibe la app

A cada mensaje del analizador se le añaden tres campos: `hablante` (`llamante` o `receptor`), `texto` y `inicio_ms`. Si el parser de la app es estricto con los campos desconocidos, añádelos como opcionales en tu clase de respuesta (`VishingResponse.kt`), por ejemplo `val hablante: String? = null`, `val texto: String? = null` y `val inicioMs: Long? = null` (con `@SerializedName("inicio_ms")` si usas Gson).

### Cómo añadir después el interruptor del analizador

Hoy no existe, pero el análisis está aislado en una sola función (`_etapa_analisis`), de modo que añadirlo después son tres líneas en `twilio_stream.py`:

```python
# junto a STT_MODE
ANALIZAR = os.getenv("VISHGUARD_ANALIZAR", "1").lower() in ("1", "true", "yes")

async def _etapa_analisis(texto: str) -> dict:
    if not ANALIZAR:
        return {"nivel_riesgo": "BAJO", "score": 0, "texto": texto}  # no llama a la IA
    return await asyncio.to_thread(analyzer.analizar_texto, texto)
```

Con `VISHGUARD_ANALIZAR=0` el resultado neutro sigue llegando a la app y no se guarda en la base de datos, porque el nivel `BAJO` no se persiste. La suite ya incluye una prueba que sustituye esa función, y demuestra que el resto de la canalización no cambia.

## Fase 6. Groq real y base de datos

```powershell
$env:VISHGUARD_STT = "groq"
$env:GROQ_API_KEY  = "<tu clave>"
```

Verifica en tu cuenta de Groq que el modelo `whisper-large-v3-turbo` esté disponible o cámbialo con `GROQ_STT_MODEL`. Reinicia y haz una llamada hablando en voz alta frases típicas de vishing (por ejemplo "necesitamos su clave bancaria urgente"). Los bloques con silencio se descartan sin llamar a la API. En este modo **sí se guardan** en la base de datos las alertas de nivel `MEDIO`, `PELIGROSO` o `FRAUDE`: compruébalo en el endpoint de historial de alertas que tengas en `/docs`.

## Qué URL usa la app Android

| Dónde corre la app | URL del WebSocket |
| --- | --- |
| Emulador de Android Studio | `ws://10.0.2.2:8000/ws/stream?numero=%2B502XXXXXXXX` |
| Celular físico en la misma Wi-Fi | `ws://<IP-de-tu-PC>:8000/ws/stream?numero=%2B502XXXXXXXX` y permitir el puerto 8000 en el Firewall de Windows |
| Cualquiera (la más simple) | `wss://xxxx.ngrok-free.app/ws/stream?numero=%2B502XXXXXXXX` |

En la URL el `+` debe ir como `%2B`. El backend normaliza el número (acepta espacios y guiones), pero un `+` sin codificar llega como espacio.

## Solución de problemas

| Síntoma | Causa probable | Qué hacer |
| --- | --- | --- |
| Al llamar: "an application error has occurred" | El webhook respondió con error o no respondió | Mira la respuesta en ngrok 4040: 500 es destino sin configurar, 403 es firma inválida, y si no aparece nada, el backend o ngrok están caídos |
| 403 desde Twilio | `PUBLIC_URL` distinta de la URL configurada en Twilio, o Auth Token equivocado | Deben coincidir exactamente (https, dominio, ruta), sin `/` final en `PUBLIC_URL` |
| Oyes "The Stream verb is not available on trial accounts" | Cuenta Trial | Haz el upgrade (Fase 4.1) |
| Suena, pero no aparece `Stream iniciado` | Twilio no pudo abrir el WebSocket | `PUBLIC_URL` debe ser `https` (el stream exige `wss`); revisa el prefijo de rutas y el depurador de Twilio |
| `Stream iniciado` sí aparece, pero la app no recibe nada | La app no está conectada con ese número | Revisa `GET /debug/connections`; el log muestra `No hay conexión activa para ***XXXX` |
| 403 al usar Swagger | `TWILIO_AUTH_TOKEN` definido | Esperado: quítalo para pruebas manuales por Swagger |
| `ModuleNotFoundError: audioop` | Python 3.13 | `pip install audioop-lts` |
| Con `groq` no llegan alertas hablando en silencio | El silencio se descarta | Habla durante la llamada |
| La URL de ngrok cambió | Dominio temporal | Actualiza `PUBLIC_URL`, reinicia uvicorn y actualiza el webhook de Twilio |
| La llamada se corta a los 10 minutos | Límite de Trial | Hacer upgrade |
| Solo llegan mensajes del llamante | Twilio no envía la pista `outbound` | Mira `pistas=` en la línea `Stream iniciado`; la pista del receptor solo fluye cuando el `<Dial>` conecta. Confirma que el webhook de Twilio sea el nuevo (`both_tracks`) y reinicia uvicorn |
| El WAV tiene un canal en silencio | Esa persona no habló o su pista no llegó | Escucha cada canal por separado y revisa `pistas=` en el log |
| Llegan mensajes del receptor antes de que conteste | La pista `outbound` incluye tono de llamada o música en espera | Es audio de Twilio, no una persona: hay que filtrarlo (por ejemplo, ignorar la pista hasta que el receptor conteste) |
| No aparece la carpeta `grabaciones` | La variable se definió después de arrancar uvicorn, o lo ejecutaste desde otra carpeta | Define `VISHGUARD_GUARDAR_WAV=1` antes de arrancar; la ruta es relativa a la carpeta actual (o fija `VISHGUARD_WAV_DIR`) |
| El log muestra `Groq 401 Invalid API Key` | Clave del analizador (`chat/completions`) inválida; no es de Whisper | No afecta a la recepción de llamadas: el analizador cae al heurístico local. Quien lo mantenga debe renovar la clave |

## Al terminar

Cierra ngrok y, si ya no usarás el número, libéralo para no pagar la renta mensual. Regenera el Auth Token si lo pegaste en algún lugar visible. Las llamadas con upgrade consumen minutos de voz, así que usa pocas llamadas cortas mientras pruebas.

## Qué no pude verificar

- Los nombres exactos de los menús de **Voice** en la consola nueva (la doc oficial solo detalla los de Messaging).
- La disponibilidad de números con voz en Guatemala y si piden *compliance profile*. Verifícalo en la pantalla de compra.
- El depósito mínimo vigente del upgrade.
- Si la opción **Custom** del panel *Try out Voice* del Trial permite pegar tu propia URL de webhook.
- Cuánto audio genera la pista `outbound` antes de que el receptor conteste (tono de llamada o silencio). Se comprueba escuchando el canal derecho del WAV de una llamada real.
- Si `both_tracks` cuenta como dos streams en la facturación de Media Streams. Revísalo en la página de precios de Twilio.

Fuentes: [Respond to incoming calls](https://www.twilio.com/docs/voice/tutorials/how-to-respond-to-incoming-phone-calls), [TwiML `<Stream>`](https://www.twilio.com/docs/voice/twiml/stream), [Trial account](https://www.twilio.com/docs/usage/trials), [Try out Voice (verbos bloqueados)](https://www.twilio.com/docs/usage/trials/try-out-voice).