-- =============================================================================
-- 003 — defasagem esperada por série
--
-- A validação de atualidade usava um limite por periodicidade, o que gerou
-- alarme falso no IBC-Br: ele é divulgado com cerca de dois meses de atraso,
-- enquanto o IPCA sai em poucas semanas. Ambos são mensais.
--
-- Defasagem esperada é característica do indicador, não da periodicidade —
-- depende do calendário de divulgação de cada um. Então vai para o catálogo,
-- pelo mesmo motivo que a periodicidade foi: metadado que governa
-- comportamento pertence ao dado, não ao código.
-- =============================================================================

ALTER TABLE bcb.series
    ADD COLUMN IF NOT EXISTS max_lag_days INTEGER;

COMMENT ON COLUMN bcb.series.max_lag_days IS
    'Defasagem máxima aceitável, em dias, antes da série ser considerada desatualizada.';

-- Valores calibrados pelo calendário de divulgação de cada indicador.
UPDATE bcb.series SET max_lag_days = 10,  updated_at = now() WHERE series_code = 432;    -- Selic: diária
UPDATE bcb.series SET max_lag_days = 75,  updated_at = now() WHERE series_code = 433;    -- IPCA mensal
UPDATE bcb.series SET max_lag_days = 75,  updated_at = now() WHERE series_code = 3698;   -- PTAX média mensal
UPDATE bcb.series SET max_lag_days = 75,  updated_at = now() WHERE series_code = 13522;  -- IPCA 12 meses
UPDATE bcb.series SET max_lag_days = 110, updated_at = now() WHERE series_code = 24364;  -- IBC-Br: ~2 meses de atraso

SELECT series_code, name, frequency, max_lag_days
  FROM bcb.series
 ORDER BY series_code;
