-- Migracion 0001: esquema inicial (seccion 4 del plan).
--
-- Nota de diseño: el plan nombraba la columna `google_place_id`. Aqui se
-- generaliza a (fuente, ref) para que el registro del ICAA, un directorio o un
-- scraper puedan convivir con Google en la misma tabla sin migracion.

BEGIN;

CREATE TYPE estado_pipeline AS ENUM (
    'nuevo',
    'calificado',
    'sitio_generado',
    'qa_aprobado',
    'contactado',
    'interesado',
    'demo_agendada',
    'negociacion',
    'cliente',
    'descartado'
);

CREATE TYPE estado_qa AS ENUM ('pendiente', 'aprobado', 'rechazado');

-- Timestamp de actualizacion automatico, reutilizado por varias tablas.
CREATE FUNCTION set_actualizado_en() RETURNS trigger AS $$
BEGIN
    NEW.actualizado_en = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;


CREATE TABLE leads (
    id                    bigserial PRIMARY KEY,

    -- Identidad en la fuente de origen.
    fuente                text        NOT NULL,
    ref                   text        NOT NULL,

    nombre_negocio        text        NOT NULL,
    nicho                 text        NOT NULL,

    telefono              text,
    whatsapp              text,
    direccion             text,
    lat                   double precision,
    lng                   double precision,
    tipos                 text[]      NOT NULL DEFAULT '{}',

    rating                numeric(2,1),
    num_resenas           integer,
    estado_negocio        text,

    tiene_sitio_web       boolean     NOT NULL DEFAULT false,
    url_sitio_actual      text,
    calidad_sitio_score   numeric(5,2),

    -- Desglose del score, no solo el total: sin esto no se puede recalibrar
    -- la ponderacion con datos reales.
    score_total           numeric(5,2),
    score_demanda         numeric(5,2),
    score_ticket          numeric(5,2),
    score_brecha          numeric(5,2),
    descartado_por        text,

    instagram_handle      text,
    instagram_bio         text,
    tiene_datos_instagram boolean     NOT NULL DEFAULT false,

    estado_pipeline       estado_pipeline NOT NULL DEFAULT 'nuevo',
    notas                 text,

    creado_en             timestamptz NOT NULL DEFAULT now(),
    actualizado_en        timestamptz NOT NULL DEFAULT now(),
    fecha_ultimo_contacto timestamptz,

    -- Un mismo negocio no se carga dos veces desde la misma fuente. Es lo que
    -- hace que re-correr una extraccion sea idempotente y barato.
    CONSTRAINT leads_fuente_ref_uniq UNIQUE (fuente, ref),
    CONSTRAINT leads_rating_valido CHECK (rating IS NULL OR rating BETWEEN 0 AND 5)
);

CREATE INDEX leads_estado_idx  ON leads (estado_pipeline);
CREATE INDEX leads_nicho_idx   ON leads (nicho);
-- Para la cola de trabajo: los mejores leads sin procesar, primero.
CREATE INDEX leads_score_idx   ON leads (score_total DESC NULLS LAST)
    WHERE estado_pipeline = 'calificado';

CREATE TRIGGER leads_actualizado_en
    BEFORE UPDATE ON leads
    FOR EACH ROW EXECUTE FUNCTION set_actualizado_en();


CREATE TABLE sitios_generados (
    id               bigserial PRIMARY KEY,
    lead_id          bigint      NOT NULL REFERENCES leads (id) ON DELETE CASCADE,

    url_demo         text,
    url_produccion   text,
    template_usado   text        NOT NULL,
    version          integer     NOT NULL DEFAULT 1,
    estado_qa        estado_qa   NOT NULL DEFAULT 'pendiente',
    reporte_qa       jsonb,
    fuente_fotos     text,

    creado_en        timestamptz NOT NULL DEFAULT now(),
    actualizado_en   timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT sitios_lead_version_uniq UNIQUE (lead_id, version)
);

CREATE INDEX sitios_lead_idx ON sitios_generados (lead_id);

CREATE TRIGGER sitios_actualizado_en
    BEFORE UPDATE ON sitios_generados
    FOR EACH ROW EXECUTE FUNCTION set_actualizado_en();


CREATE TABLE mensajes_outreach (
    id              bigserial PRIMARY KEY,
    lead_id         bigint      NOT NULL REFERENCES leads (id) ON DELETE CASCADE,

    canal           text        NOT NULL,
    contenido       text        NOT NULL,
    fecha_envio     timestamptz NOT NULL DEFAULT now(),
    respuesta       text,
    fecha_respuesta timestamptz,

    CONSTRAINT mensajes_respuesta_coherente
        CHECK ((respuesta IS NULL) = (fecha_respuesta IS NULL))
);

CREATE INDEX mensajes_lead_idx  ON mensajes_outreach (lead_id, fecha_envio DESC);

COMMIT;
