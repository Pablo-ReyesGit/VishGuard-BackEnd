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

El archivo `tests/simular_twilio.py` hace de app Android (se conecta a `/ws/stream`) y de Twilio (envía `connected`, `start` con `customParameters`, frames `media` a ritmo real y `stop`). Con el backend corriendo y `VISHGUARD_STT=simulado`:

```powershell
python tests\simular_twilio.py --numero +502XXXXXXXX --segundos 7
```

Salida esperada, validada contra un servidor real:

```
[APP]    conectada a /ws/stream
[TWILIO] conectado a /ws/twilio
[TWILIO] start enviado (to=+502...); enviando 7 s de audio...
[APP]    ALERTA #1: nivel=... score=...
[APP]    ALERTA #2: ...
[TWILIO] stop enviado
[APP]    ALERTA #3: ...
RESULTADO: OK, la app recibió 3 alerta(s).
```

Salen 3 alertas porque 7 s son dos bloques de 3 s más un remanente de 1 s (se procesa al recibir `stop`). En la consola de uvicorn deben aparecer `Conexión WebSocket establecida con Twilio`, `Stream iniciado (callSid=CA_SIMULADO, destino=***XXXX)`, un `[VishGuard] riesgo=…` por alerta y `Transmisión finalizada por Twilio`.

Variantes útiles: `--url wss://xxxx.ngrok-free.app` (probar a través de ngrok), `--prefijo /api/v1` si incluyes los routers con prefijo, `--token <JWT>` si activas `WS_AUTH_REQUIRED`. Con `VISHGUARD_STT=groq` el simulador manda silencio, que se descarta: para probar Groq usa una llamada real.

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
4. **Consola de uvicorn:** `Stream iniciado (callSid=CA…, destino=***XXXX)` y, cada \~3 s de audio, `[VishGuard] riesgo=… score=…`.
5. **La app** recibe una alerta por cada bloque analizado.
6. Al colgar: `Transmisión finalizada por Twilio`.

Con `VISHGUARD_STT=simulado` la alerta llega cada 3 s con el texto fijo, sin importar lo que se hable, y no se guarda en la base de datos. Si la llamada falla, abre los registros de llamadas y el depurador de Twilio (en la Legacy Console están bajo **Monitor → Logs**) y busca la llamada por su hora.

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

## Al terminar

Cierra ngrok y, si ya no usarás el número, libéralo para no pagar la renta mensual. Regenera el Auth Token si lo pegaste en algún lugar visible. Las llamadas con upgrade consumen minutos de voz, así que usa pocas llamadas cortas mientras pruebas.

## Qué no pude verificar

- Los nombres exactos de los menús de **Voice** en la consola nueva (la doc oficial solo detalla los de Messaging).
- La disponibilidad de números con voz en Guatemala y si piden *compliance profile*. Verifícalo en la pantalla de compra.
- El depósito mínimo vigente del upgrade.
- Si la opción **Custom** del panel *Try out Voice* del Trial permite pegar tu propia URL de webhook.

Fuentes: [Respond to incoming calls](https://www.twilio.com/docs/voice/tutorials/how-to-respond-to-incoming-phone-calls), [TwiML `<Stream>`](https://www.twilio.com/docs/voice/twiml/stream), [Trial account](https://www.twilio.com/docs/usage/trials), [Try out Voice (verbos bloqueados)](https://www.twilio.com/docs/usage/trials/try-out-voice).