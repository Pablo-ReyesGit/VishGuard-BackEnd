# Asociación de llamadas con usuarios

El campo `phone_number` es opcional para conservar las cuentas existentes y único
entre las cuentas que lo registran. Se usa formato internacional con `+` y código
de país. El backend elimina espacios, guiones y paréntesis. No verifica posesión
del número mediante SMS: para las pruebas, registrar solo teléfonos propios.

## Base de datos

- El 15 de octubre de 2026 se aplicó `002_sqlmodel_schema.sql` a la base configurada
  en `.env`, después de comprobar que las cinco tablas anteriores estaban vacías.
  Se crearon `user` (incluido `phone_number`) y la nueva `alerta`. La tabla de alertas
  anterior se conservó como `alerta_legacy`; las demás tablas no se modificaron.
  Se verificaron columnas, tipos, nulabilidad, índices únicos y la clave foránea
  antes de confirmar la transacción. No volver a ejecutar `002` en esa base.
- Si ya existe la tabla SQLModel `user`, revisar y ejecutar manualmente
  `001_user_phone.sql` únicamente si falta el campo de teléfono. No es necesario
  en la base donde se aplicó `002`, pues esa migración ya incluye el campo.
- Si la base está vacía, `init_db()` creará el campo con el resto de las tablas.
- Antes de arrancar, revisar que `alerta` tenga las columnas del modelo
  `models/alert.py`. La tabla antigua con `analisis_id`, `nivel` y `mensaje` no es
  compatible. `create_all()` no convierte esa tabla y este script tampoco lo hace.
  Hace falta una migración específica después de inspeccionar el esquema y datos.

## Prueba con cada integrante

1. Iniciar sesión y guardar su teléfono receptor mediante
   `PATCH /api/v1/users/me`, con el JWT como `Authorization: Bearer <token>`:

   ```json
   {"phone_number": "+50212345678"}
   ```

   También se acepta en registro (`POST /api/v1/users/signup`) y en creación o
   actualización por un administrador. Un teléfono ya registrado responde 409;
   un formato inválido responde 422. `null` elimina la asociación del perfil.

2. Configurar `VISHGUARD_DESTINO` en el backend con ese mismo teléfono y reiniciar
   después de aplicar las migraciones necesarias. Esa variable sigue seleccionando un único
   destinatario por instancia. El número de Twilio es el número al que llaman.
3. Al analizar una llamada real, el servicio busca la cuenta activa por el teléfono
   receptor y guarda su `usuario_id`. Si no hay cuenta asociada, no guarda la alerta
   y escribe el motivo en el log. El modo STT simulado sigue sin guardar alertas.
4. Consultar `GET /alerts` con el JWT para ver únicamente las alertas propias.

Si `WS_AUTH_REQUIRED=true`, la app debe enviar el JWT a `/ws/stream` y el número
de la suscripción debe coincidir con el teléfono de su perfil. El comportamiento
de pruebas sin esa opción sigue permitiendo suscripciones sin autenticación.
