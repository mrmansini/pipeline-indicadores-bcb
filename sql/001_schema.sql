-- =============================================================================
-- BCB indicators pipeline — initial schema
--
-- Three tables:
--   series        catalog of tracked indicators
--   observations  values over time (the fact table)
--   runs          execution log, one row per series per pipeline run
--
-- This script is idempotent: it can be executed more than once safely.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS bcb;


-- -----------------------------------------------------------------------------
-- series — catalog of tracked indicators
-- The primary key is the SGS series code, which is already unique and stable.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bcb.series (
    series_code   INTEGER      PRIMARY KEY,
    name          TEXT         NOT NULL,
    unit          TEXT,
    frequency     TEXT,
    source        TEXT         NOT NULL DEFAULT 'BCB/SGS',
    is_active     BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);

COMMENT ON TABLE  bcb.series IS 'Catalog of economic indicators tracked by the pipeline.';
COMMENT ON COLUMN bcb.series.series_code IS 'Series code in the Brazilian Central Bank SGS system.';
COMMENT ON COLUMN bcb.series.is_active IS 'Inactive series stay in history but are no longer collected.';


-- -----------------------------------------------------------------------------
-- observations — values over time
--
-- The composite primary key (series_code, reference_date) is what makes the
-- load idempotent: the table structure itself prevents the same observation
-- from being stored twice. Re-running the pipeline updates, never duplicates.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bcb.observations (
    series_code     INTEGER      NOT NULL REFERENCES bcb.series (series_code),
    reference_date  DATE         NOT NULL,
    value           NUMERIC(18,6),
    ingested_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (series_code, reference_date)
);

COMMENT ON TABLE  bcb.observations IS 'Observed values for each series over time.';
COMMENT ON COLUMN bcb.observations.value IS 'NUMERIC, not FLOAT: economic values must not carry binary rounding error.';

-- Index for the most common query: one series over a date range.
CREATE INDEX IF NOT EXISTS ix_observations_series_date
    ON bcb.observations (series_code, reference_date DESC);


-- -----------------------------------------------------------------------------
-- runs — execution log
--
-- Without this, "how fresh is this number?" and "why did yesterday's load
-- bring nothing?" become guesswork. A pipeline that does not record its own
-- execution is not auditable.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bcb.runs (
    id                  BIGSERIAL    PRIMARY KEY,
    series_code         INTEGER      REFERENCES bcb.series (series_code),
    started_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    finished_at         TIMESTAMPTZ,
    status              TEXT         NOT NULL DEFAULT 'RUNNING',
    requested_start_date DATE,
    requested_end_date   DATE,
    records_received    INTEGER      NOT NULL DEFAULT 0,
    records_inserted    INTEGER      NOT NULL DEFAULT 0,
    records_updated     INTEGER      NOT NULL DEFAULT 0,
    attempts            INTEGER      NOT NULL DEFAULT 1,
    error_message       TEXT,
    CONSTRAINT ck_runs_status
        CHECK (status IN ('RUNNING', 'SUCCESS', 'FAILED', 'NO_DATA'))
);

COMMENT ON TABLE bcb.runs IS 'Audit log: one row per series per pipeline run.';

CREATE INDEX IF NOT EXISTS ix_runs_started_at
    ON bcb.runs (started_at DESC);


-- -----------------------------------------------------------------------------
-- Tracked series
--
-- Series names are kept in Portuguese on purpose: they are the official names
-- of the indicators, not a naming choice. Identifiers are English; data is not.
--
-- ON CONFLICT DO UPDATE: if the series already exists, refresh its metadata
-- instead of failing. Same upsert pattern used when loading observations.
-- -----------------------------------------------------------------------------
INSERT INTO bcb.series (series_code, name, unit, frequency) VALUES
    (   432, 'Taxa Selic — meta definida pelo Copom',    '% a.a.',   'daily'),
    (   433, 'IPCA — variação mensal',                   '% no mês', 'monthly'),
    ( 13522, 'IPCA — acumulado em 12 meses',             '% em 12m', 'monthly'),
    (  3698, 'Dólar PTAX — venda',                       'R$/US$',   'daily'),
    ( 24364, 'IBC-Br — índice de atividade econômica',   'índice',   'monthly')
ON CONFLICT (series_code) DO UPDATE SET
    name       = EXCLUDED.name,
    unit       = EXCLUDED.unit,
    frequency  = EXCLUDED.frequency,
    updated_at = now();
