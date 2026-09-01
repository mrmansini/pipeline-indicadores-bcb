-- =============================================================================
-- 007 — acesso somente leitura e view para ferramenta de BI externa
--
-- Duas mudanças, com motivos diferentes.
--
-- 1) Um usuário separado, só de leitura, para a ferramenta de BI. A conexão
--    vai ser configurada numa ferramenta de terceiro e o relatório vai ficar
--    público — dar a esse caminho a mesma credencial que escreve no banco
--    seria entregar permissão de escrita a quem só precisa consultar.
--
-- 2) Uma view desnormalizada. O modelo estrela é o certo para o Power BI, que
--    entende relacionamento entre tabelas. Ferramentas mais simples trabalham
--    melhor com uma tabela só, já com as dimensões resolvidas.
-- =============================================================================

SET client_encoding TO 'UTF8';


-- -----------------------------------------------------------------------------
-- View desnormalizada: fato + dimensões numa consulta só
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW analytics.v_bi_observations AS
SELECT
    o.reference_date,
    s.series_code,
    COALESCE(s.short_name, s.name)              AS indicator,
    s.name                                      AS indicator_full_name,
    s.unit,
    s.frequency,
    o.value,
    EXTRACT(YEAR  FROM o.reference_date)::int   AS year,
    EXTRACT(MONTH FROM o.reference_date)::int   AS month_number,
    to_char(o.reference_date, 'YYYY-MM')        AS year_month,
    date_trunc('month', o.reference_date)::date AS month_start
FROM bcb.observations o
JOIN bcb.series s USING (series_code)
WHERE o.value IS NOT NULL;

COMMENT ON VIEW analytics.v_bi_observations IS
    'Fato e dimensões numa tabela só, para ferramentas de BI que não modelam relacionamento.';


-- -----------------------------------------------------------------------------
-- Usuário somente leitura
--
-- IMPORTANTE: troque a senha abaixo antes de executar, e NÃO faça commit
-- deste arquivo com a senha real. Este arquivo vai para o repositório com o
-- texto de placeholder.
-- -----------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bi_reader') THEN
        CREATE ROLE bi_reader WITH LOGIN PASSWORD 'TROQUE_ESTA_SENHA';
    END IF;
END
$$;

-- Acesso apenas ao schema de consumo. O schema bcb, onde o pipeline escreve,
-- fica fora do alcance dessa credencial.
GRANT USAGE ON SCHEMA analytics TO bi_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA analytics TO bi_reader;

-- As views de analytics leem tabelas de bcb; sem USAGE no schema de origem, a
-- consulta falha. SELECT nas tabelas continua negado.
GRANT USAGE ON SCHEMA bcb TO bi_reader;
GRANT SELECT ON bcb.series, bcb.observations, bcb.runs TO bi_reader;

-- View criada depois desta migração já nasce legível pela ferramenta de BI,
-- sem precisar rodar GRANT de novo.
ALTER DEFAULT PRIVILEGES IN SCHEMA analytics GRANT SELECT ON TABLES TO bi_reader;

-- Garantia explícita: nenhuma permissão de escrita, em nenhum schema.
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA bcb FROM bi_reader;
REVOKE CREATE ON SCHEMA analytics FROM bi_reader;
REVOKE CREATE ON SCHEMA bcb FROM bi_reader;


-- Conferência.
SELECT rolname, rolcanlogin, rolsuper, rolcreatedb
  FROM pg_roles
 WHERE rolname IN ('bi_reader');

SELECT count(*) AS linhas_disponiveis FROM analytics.v_bi_observations;
