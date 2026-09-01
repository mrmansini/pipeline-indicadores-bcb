-- 008: corrige fuso horário e adiciona nome curto em v_pipeline_health
--
-- Os timestamps de bcb.runs são gravados em UTC, e o painel exibia a carga das
-- 07:00 BRT como 04:50. A conversão para America/Sao_Paulo é feita aqui, na
-- camada de consumo, para que o dado bruto continue em UTC.
--
-- O nome curto vem do catálogo: o nome oficial é longo demais para a tabela do
-- painel e aparecia truncado.
--
-- DROP é necessário porque CREATE OR REPLACE não permite alterar o tipo de
-- coluna existente.

DROP VIEW IF EXISTS analytics.v_pipeline_health;

CREATE VIEW analytics.v_pipeline_health AS
 SELECT r.id AS run_id,
    r.series_code,
    s.name AS series_name,
    COALESCE(s.short_name, s.name) AS series_short_name,
    (r.started_at AT TIME ZONE 'America/Sao_Paulo') AS started_at,
    (r.finished_at AT TIME ZONE 'America/Sao_Paulo') AS finished_at,
    r.finished_at - r.started_at AS duration,
    r.status,
    r.records_received,
    r.records_inserted,
    r.records_updated,
    r.error_message,
    (r.started_at AT TIME ZONE 'America/Sao_Paulo')::date AS run_date
   FROM bcb.runs r
     LEFT JOIN bcb.series s USING (series_code);

GRANT SELECT ON analytics.v_pipeline_health TO bi_reader;