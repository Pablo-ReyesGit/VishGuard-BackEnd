-- Marca el origen de las alertas sin cambiar ni eliminar registros existentes.
-- Las alertas anteriores y las llamadas reales conservan es_simulacion = FALSE.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
ALTER TABLE public.alerta
    ADD COLUMN IF NOT EXISTS es_simulacion BOOLEAN NOT NULL DEFAULT FALSE;
COMMIT;
