-- =============================================================================
-- 005 — correção de encoding nos nomes das séries
--
-- Os nomes foram gravados corrompidos: o psql no Windows assume WIN1252 como
-- codificação de cliente, e os arquivos .sql deste projeto estão em UTF-8.
-- O resultado foi dupla conversão — "Dólar" virou "DÃ³lar", e o travessão
-- virou "â€"".
--
-- A linha abaixo é o que impede o problema de se repetir: ela declara ao
-- servidor como o conteúdo deste arquivo está codificado, em vez de deixar
-- o padrão do sistema operacional decidir.
-- =============================================================================

SET client_encoding TO 'UTF8';

UPDATE bcb.series SET name = 'Taxa Selic - meta definida pelo Copom',    updated_at = now() WHERE series_code = 432;
UPDATE bcb.series SET name = 'IPCA - variação mensal',                   updated_at = now() WHERE series_code = 433;
UPDATE bcb.series SET name = 'IPCA - acumulado em 12 meses',             updated_at = now() WHERE series_code = 13522;
UPDATE bcb.series SET name = 'Dólar PTAX - venda, média mensal',         updated_at = now() WHERE series_code = 3698;
UPDATE bcb.series SET name = 'IBC-Br - índice de atividade econômica',   updated_at = now() WHERE series_code = 24364;

UPDATE bcb.series SET unit = '% a.a.'   WHERE series_code = 432;
UPDATE bcb.series SET unit = '% no mês' WHERE series_code IN (433);
UPDATE bcb.series SET unit = '% em 12m' WHERE series_code = 13522;
UPDATE bcb.series SET unit = 'R$/US$'   WHERE series_code = 3698;
UPDATE bcb.series SET unit = 'índice'   WHERE series_code = 24364;

-- Conferência: se algum nome ainda contiver a sequência típica da dupla
-- conversão, a correção não pegou.
SELECT series_code,
       name,
       unit,
       name LIKE '%Ã%' OR name LIKE '%â€%' AS ainda_corrompido
  FROM bcb.series
 ORDER BY series_code;
