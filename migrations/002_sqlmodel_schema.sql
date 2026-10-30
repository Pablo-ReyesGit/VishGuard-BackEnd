-- Migracion aplicada al esquema anterior vacio de VishGuard.
-- Conserva usuario, llamada, analisis y patron_deteccion.
-- Conserva la alerta anterior como alerta_legacy; no borra tablas.
-- Incluye phone_number: no ejecutar 001 antes de esta migracion.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
DO $$
BEGIN
    IF to_regclass('public."user"') IS NOT NULL
       OR to_regclass('public.alerta_legacy') IS NOT NULL THEN
        RAISE EXCEPTION 'Esquema ya migrado o no esperado; revisar antes de continuar';
    END IF;
END $$;
LOCK TABLE public.usuario, public.alerta IN ACCESS EXCLUSIVE MODE;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM public.usuario)
       OR EXISTS (SELECT 1 FROM public.alerta) THEN
        RAISE EXCEPTION 'Hay datos antiguos; se necesita una migracion de datos';
    END IF;
END $$;
ALTER TABLE public.alerta RENAME TO alerta_legacy;
-- Liberar los nombres de objetos asociados a la tabla anterior.
ALTER INDEX IF EXISTS public.alerta_pkey RENAME TO alerta_legacy_pkey;
ALTER SEQUENCE IF EXISTS public.alerta_id_seq RENAME TO alerta_legacy_id_seq;


CREATE TABLE "user" (
	id SERIAL NOT NULL,
	email VARCHAR(255) NOT NULL,
	hashed_password VARCHAR NOT NULL,
	is_active BOOLEAN NOT NULL,
	is_superuser BOOLEAN NOT NULL,
	full_name VARCHAR(255),
	phone_number VARCHAR(16),
	PRIMARY KEY (id)
);

CREATE UNIQUE INDEX ix_user_email ON "user" (email);

CREATE UNIQUE INDEX ix_user_phone_number ON "user" (phone_number);

CREATE TABLE alerta (
	id SERIAL NOT NULL,
	usuario_id INTEGER NOT NULL,
	nivel_riesgo VARCHAR(20) NOT NULL,
	score INTEGER NOT NULL,
	mensaje_alerta VARCHAR NOT NULL,
	recomendacion VARCHAR,
	mostrada BOOLEAN NOT NULL,
	fecha_alerta TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(usuario_id) REFERENCES "user" (id)
);

CREATE INDEX ix_alerta_usuario_id ON alerta (usuario_id);

COMMIT;
