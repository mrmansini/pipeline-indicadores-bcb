-- =============================================================================
-- Pipeline de indicadores do BCB — schema inicial
--
-- Modelo em três tabelas:
--   series      catálogo dos indicadores acompanhados
--   observacoes valores no tempo (o fato)
--   execucoes   log de cada rodada do pipeline
--
-- Script idempotente: pode ser executado mais de uma vez sem erro.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS bcb;


-- -----------------------------------------------------------------------------
-- series — catálogo dos indicadores
-- A chave primária é o código da série no SGS do BCB, que já é único e estável.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bcb.series (
    codigo_serie   INTEGER      PRIMARY KEY,
    nome           TEXT         NOT NULL,
    unidade        TEXT,
    periodicidade  TEXT,
    fonte          TEXT         NOT NULL DEFAULT 'BCB/SGS',
    ativo          BOOLEAN      NOT NULL DEFAULT TRUE,
    criado_em      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    atualizado_em  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

COMMENT ON TABLE  bcb.series IS 'Catálogo dos indicadores acompanhados pelo pipeline.';
COMMENT ON COLUMN bcb.series.codigo_serie IS 'Código da série no SGS do Banco Central.';
COMMENT ON COLUMN bcb.series.ativo IS 'Séries inativas permanecem no histórico mas não são coletadas.';


-- -----------------------------------------------------------------------------
-- observacoes — os valores no tempo
--
-- A chave primária composta (codigo_serie, data_referencia) é o que torna a
-- carga idempotente: a própria estrutura da tabela impede que a mesma
-- observação entre duas vezes. Rodar o pipeline de novo atualiza, não duplica.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bcb.observacoes (
    codigo_serie    INTEGER      NOT NULL REFERENCES bcb.series (codigo_serie),
    data_referencia DATE         NOT NULL,
    valor           NUMERIC(18,6),
    ingerido_em     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    atualizado_em   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (codigo_serie, data_referencia)
);

COMMENT ON TABLE  bcb.observacoes IS 'Valores observados de cada série ao longo do tempo.';
COMMENT ON COLUMN bcb.observacoes.valor IS 'NUMERIC, não FLOAT: valor econômico não admite erro de arredondamento binário.';

-- Índice para a consulta mais comum: uma série num intervalo de datas.
CREATE INDEX IF NOT EXISTS ix_observacoes_serie_data
    ON bcb.observacoes (codigo_serie, data_referencia DESC);


-- -----------------------------------------------------------------------------
-- execucoes — log de cada rodada
--
-- Sem isso, "de quando é esse número?" e "por que a carga de ontem falhou?"
-- viram chute. Um pipeline que não registra a própria execução não é auditável.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bcb.execucoes (
    id                     BIGSERIAL    PRIMARY KEY,
    codigo_serie           INTEGER      REFERENCES bcb.series (codigo_serie),
    iniciado_em            TIMESTAMPTZ  NOT NULL DEFAULT now(),
    finalizado_em          TIMESTAMPTZ,
    status                 TEXT         NOT NULL DEFAULT 'EM_ANDAMENTO',
    data_inicial_solicitada DATE,
    data_final_solicitada   DATE,
    registros_recebidos    INTEGER      NOT NULL DEFAULT 0,
    registros_inseridos    INTEGER      NOT NULL DEFAULT 0,
    registros_atualizados  INTEGER      NOT NULL DEFAULT 0,
    tentativas             INTEGER      NOT NULL DEFAULT 1,
    mensagem_erro          TEXT,
    CONSTRAINT ck_execucoes_status
        CHECK (status IN ('EM_ANDAMENTO', 'SUCESSO', 'FALHA', 'SEM_DADOS'))
);

COMMENT ON TABLE bcb.execucoes IS 'Log de auditoria: uma linha por série por rodada do pipeline.';

CREATE INDEX IF NOT EXISTS ix_execucoes_iniciado_em
    ON bcb.execucoes (iniciado_em DESC);


-- -----------------------------------------------------------------------------
-- Séries acompanhadas
--
-- ON CONFLICT DO UPDATE: se a série já existir, atualiza os metadados em vez
-- de falhar. É o mesmo padrão de upsert usado na ingestão das observações.
-- -----------------------------------------------------------------------------
INSERT INTO bcb.series (codigo_serie, nome, unidade, periodicidade) VALUES
    (   432, 'Taxa Selic — meta definida pelo Copom', '% a.a.',      'diaria'),
    (   433, 'IPCA — variação mensal',                '% no mês',    'mensal'),
    ( 13522, 'IPCA — acumulado em 12 meses',          '% em 12m',    'mensal'),
    (  3698, 'Dólar PTAX — venda',                    'R$/US$',      'diaria'),
    ( 24364, 'IBC-Br — índice de atividade econômica','índice',      'mensal')
ON CONFLICT (codigo_serie) DO UPDATE SET
    nome          = EXCLUDED.nome,
    unidade       = EXCLUDED.unidade,
    periodicidade = EXCLUDED.periodicidade,
    atualizado_em = now();
