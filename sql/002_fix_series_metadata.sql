-- =============================================================================
-- 002 — correção de metadado do catálogo
--
-- A série 3698 foi cadastrada como diária, mas é a MÉDIA MENSAL do dólar
-- PTAX. O erro só apareceu ao conferir a contagem depois da carga: 139
-- observações em 11 anos, sempre no primeiro dia do mês.
--
-- Como a periodicidade agora governa o tamanho da janela de coleta, um
-- metadado errado no catálogo vira comportamento errado na ingestão. O
-- catálogo deixou de ser documentação e virou configuração.
-- =============================================================================

UPDATE bcb.series
   SET name       = 'Dólar PTAX — venda, média mensal',
       frequency  = 'monthly',
       updated_at = now()
 WHERE series_code = 3698;

-- Conferência: nenhuma série pode ficar com periodicidade fora do previsto,
-- porque o pipeline usa esse valor para decidir o tamanho da janela.
SELECT series_code, name, frequency
  FROM bcb.series
 ORDER BY series_code;
