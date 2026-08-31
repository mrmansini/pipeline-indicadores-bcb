-- =============================================================================
-- 006 — nome curto para exibição
--
-- O nome oficial da série serve ao catálogo e à rastreabilidade, mas é longo
-- demais para legenda, segmentação e título de visual. Em vez de renomear no
-- Power BI — o que valeria só para aquele arquivo —, o nome de exibição entra
-- no catálogo, ao lado do oficial. Qualquer ferramenta que consuma o dado
-- depois recebe os dois.
-- =============================================================================

SET client_encoding TO 'UTF8';

ALTER TABLE bcb.series
    ADD COLUMN IF NOT EXISTS short_name TEXT;

COMMENT ON COLUMN bcb.series.short_name IS
    'Nome curto para exibição em interface. O nome oficial fica em name.';

UPDATE bcb.series SET short_name = 'Taxa Selic',                updated_at = now() WHERE series_code = 432;
UPDATE bcb.series SET short_name = 'IPCA mensal',               updated_at = now() WHERE series_code = 433;
UPDATE bcb.series SET short_name = 'IPCA acumulado (12 meses)', updated_at = now() WHERE series_code = 13522;
UPDATE bcb.series SET short_name = 'Dólar PTAX',                updated_at = now() WHERE series_code = 3698;
UPDATE bcb.series SET short_name = 'IBC-BR',                    updated_at = now() WHERE series_code = 24364;

-- A coluna nova é acrescentada ao fim da view: CREATE OR REPLACE exige que as
-- colunas existentes mantenham nome, tipo e ordem.
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
    s.is_active,
    COALESCE(s.short_name, s.name)            AS short_name
FROM bcb.series s;

SELECT series_code, short_name, name FROM bcb.series ORDER BY series_code;
