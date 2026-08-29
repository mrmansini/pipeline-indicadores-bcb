-- =============================================================================
-- 004 — camada analítica
--
-- Views desenhadas para consumo em BI, em modelo estrela: duas dimensões
-- (série e calendário) e um fato (observações), mais uma view de saúde do
-- pipeline.
--
-- A regra de negócio fica aqui, versionada em Git e auditável em SQL, e não
-- espalhada em DAX dentro de um arquivo binário. O Power BI recebe o dado
-- com o significado já resolvido e cuida de recorte, filtro e visual.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS analytics;


-- -----------------------------------------------------------------------------
-- dim_series — dimensão de indicador
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW analytics.dim_series AS
SELECT
    s.series_code,
    s.name                                    AS series_name,
    s.unit,
    s.frequency,
    CASE s.frequency
        WHEN 'daily'   THEN 'Diária'
        WHEN 'monthly' THEN 'Mensal'
        ELSE initcap(s.frequency)
    END                                       AS frequency_label,
    s.source,
    s.is_active
FROM bcb.series s;

COMMENT ON VIEW analytics.dim_series IS 'Dimensão de indicador para consumo em BI.';


-- -----------------------------------------------------------------------------
-- dim_calendar — dimensão de tempo
--
-- Gerada a partir do intervalo real das observações. Sem uma dimensão de
-- tempo própria, inteligência de tempo em BI depende da tabela de fato, que
-- tem buracos: série diária não tem fim de semana, série mensal só tem o
-- primeiro dia do mês.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW analytics.dim_calendar AS
WITH bounds AS (
    SELECT
        COALESCE(min(reference_date), CURRENT_DATE) AS min_date,
        GREATEST(COALESCE(max(reference_date), CURRENT_DATE), CURRENT_DATE) AS max_date
    FROM bcb.observations
),
days AS (
    SELECT generate_series(b.min_date, b.max_date, INTERVAL '1 day')::date AS date_key
    FROM bounds b
)
SELECT
    d.date_key,
    EXTRACT(YEAR    FROM d.date_key)::int      AS year,
    EXTRACT(MONTH   FROM d.date_key)::int      AS month_number,
    EXTRACT(QUARTER FROM d.date_key)::int      AS quarter_number,
    'T' || EXTRACT(QUARTER FROM d.date_key)::int AS quarter_label,
    to_char(d.date_key, 'YYYY-MM')             AS year_month,
    (ARRAY['Janeiro','Fevereiro','Março','Abril','Maio','Junho',
           'Julho','Agosto','Setembro','Outubro','Novembro','Dezembro']
     )[EXTRACT(MONTH FROM d.date_key)::int]    AS month_name,
    date_trunc('month', d.date_key)::date      AS month_start,
    EXTRACT(ISODOW FROM d.date_key)::int       AS weekday_number,
    EXTRACT(ISODOW FROM d.date_key) < 6        AS is_weekday
FROM days d;

COMMENT ON VIEW analytics.dim_calendar IS 'Dimensão de tempo contínua, sem lacunas.';


-- -----------------------------------------------------------------------------
-- fct_observations — fato
--
-- Grão: uma linha por série por data de referência. Observação sem valor é
-- descartada aqui: nulo é informação para a validação, ruído para o gráfico.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW analytics.fct_observations AS
SELECT
    o.series_code,
    o.reference_date,
    o.value,
    o.updated_at
FROM bcb.observations o
WHERE o.value IS NOT NULL;

COMMENT ON VIEW analytics.fct_observations IS 'Fato: valor observado por série e data.';


-- -----------------------------------------------------------------------------
-- v_series_latest — cartão de resumo
--
-- O valor mais recente de cada série, com o anterior e a variação. Resolver
-- isso em SQL, com window function, é mais barato e mais legível do que a
-- medida DAX equivalente.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW analytics.v_series_latest AS
WITH ranked AS (
    SELECT
        o.series_code,
        o.reference_date,
        o.value,
        ROW_NUMBER() OVER (PARTITION BY o.series_code ORDER BY o.reference_date DESC) AS rn,
        LEAD(o.value)          OVER (PARTITION BY o.series_code ORDER BY o.reference_date DESC) AS previous_value,
        LEAD(o.reference_date) OVER (PARTITION BY o.series_code ORDER BY o.reference_date DESC) AS previous_date
    FROM bcb.observations o
    WHERE o.value IS NOT NULL
)
SELECT
    s.series_code,
    s.name                                     AS series_name,
    s.unit,
    s.frequency,
    r.reference_date                           AS latest_date,
    r.value                                    AS latest_value,
    r.previous_date,
    r.previous_value,
    r.value - r.previous_value                 AS change_absolute,
    CASE
        WHEN r.previous_value IS NULL OR r.previous_value = 0 THEN NULL
        ELSE (r.value - r.previous_value) / abs(r.previous_value)
    END                                        AS change_relative,
    CURRENT_DATE - r.reference_date            AS lag_days,
    s.max_lag_days,
    (CURRENT_DATE - r.reference_date) > COALESCE(s.max_lag_days, 75) AS is_stale
FROM ranked r
JOIN bcb.series s USING (series_code)
WHERE r.rn = 1;

COMMENT ON VIEW analytics.v_series_latest IS 'Último valor de cada série, com variação e defasagem.';


-- -----------------------------------------------------------------------------
-- v_pipeline_health — saúde da ingestão
--
-- Um painel de indicadores que não mostra a saúde da própria carga esconde
-- justamente o que o leitor precisa saber para confiar no número.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW analytics.v_pipeline_health AS
SELECT
    r.id                                       AS run_id,
    r.series_code,
    s.name                                     AS series_name,
    r.started_at,
    r.finished_at,
    r.finished_at - r.started_at               AS duration,
    r.status,
    r.records_received,
    r.records_inserted,
    r.records_updated,
    r.error_message,
    r.started_at::date                         AS run_date
FROM bcb.runs r
LEFT JOIN bcb.series s USING (series_code);

COMMENT ON VIEW analytics.v_pipeline_health IS 'Histórico de execuções do pipeline para o painel de qualidade.';


-- Conferência rápida.
SELECT series_name, latest_date, latest_value, lag_days, is_stale
  FROM analytics.v_series_latest
 ORDER BY series_code;
