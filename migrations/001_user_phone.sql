-- Ejecutar manualmente en la base de VishGuard, después de revisar su esquema.
-- Requiere la tabla SQLModel "user". No modifica las tablas antiguas de alertas.
BEGIN;
ALTER TABLE "user" ADD COLUMN IF NOT EXISTS phone_number VARCHAR(16);
CREATE UNIQUE INDEX IF NOT EXISTS ix_user_phone_number ON "user" (phone_number);
COMMIT;
