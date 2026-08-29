"""
Acesso ao banco.

Concentra tudo que fala com o PostgreSQL: conexão, upsert das observações e
registro do log de execução. O resto do projeto não escreve SQL.
"""

import logging
from datetime import date

import psycopg

from bcb_client import Observation
from config import BATCH_SIZE, DATABASE_URL

logger = logging.getLogger(__name__)


def connect() -> psycopg.Connection:
    """Abre uma conexão. O commit é explícito, controlado por quem chama."""
    return psycopg.connect(DATABASE_URL)


def list_active_series(conn: psycopg.Connection) -> list[tuple[int, str, str | None]]:
    """Séries que devem ser coletadas, com a periodicidade que rege a coleta."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT series_code, name, frequency
              FROM bcb.series
             WHERE is_active
             ORDER BY series_code
            """
        )
        return cur.fetchall()


def get_last_reference_date(conn: psycopg.Connection, series_code: int) -> date | None:
    """Data da observação mais recente já armazenada para a série."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT max(reference_date) FROM bcb.observations WHERE series_code = %s",
            (series_code,),
        )
        return cur.fetchone()[0]


def start_run(
    conn: psycopg.Connection, series_code: int, start: date, end: date
) -> int:
    """Abre o registro de execução e devolve o id."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO bcb.runs
                (series_code, requested_start_date, requested_end_date, status)
            VALUES (%s, %s, %s, 'RUNNING')
            RETURNING id
            """,
            (series_code, start, end),
        )
        return cur.fetchone()[0]


def finish_run(
    conn: psycopg.Connection,
    run_id: int,
    status: str,
    received: int = 0,
    inserted: int = 0,
    updated: int = 0,
    error_message: str | None = None,
) -> None:
    """Fecha o registro de execução com o resultado."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE bcb.runs
               SET status            = %s,
                   finished_at       = now(),
                   records_received  = %s,
                   records_inserted  = %s,
                   records_updated   = %s,
                   error_message     = %s
             WHERE id = %s
            """,
            (status, received, inserted, updated, error_message, run_id),
        )


def upsert_observations(
    conn: psycopg.Connection, series_code: int, observations: list[Observation]
) -> tuple[int, int]:
    """
    Grava as observações e devolve (inseridas, atualizadas).

    Dois detalhes que fazem esta função ser o centro do pipeline:

    1. `ON CONFLICT ... DO UPDATE` com a chave (series_code, reference_date):
       rodar de novo atualiza em vez de duplicar. A garantia é da estrutura
       da tabela, não da esperteza do código.

    2. `WHERE ... IS DISTINCT FROM`: se o valor não mudou, a linha não é
       tocada. Por isso, numa recarga, inseridas + atualizadas é menor que
       recebidas — o que sobra é o que já estava correto.

    O `RETURNING (xmax = 0)` é um idioma do PostgreSQL: em uma linha recém
    inserida, xmax é zero; em uma atualizada, não. É assim que dá para
    distinguir os dois casos num único comando.
    """
    inserted = updated = 0

    with conn.cursor() as cur:
        for offset in range(0, len(observations), BATCH_SIZE):
            batch = observations[offset : offset + BATCH_SIZE]

            # Os placeholders são gerados aqui, a partir do tamanho do lote —
            # nunca a partir de dado externo. Os valores seguem parametrizados.
            placeholders = ", ".join(["(%s, %s, %s)"] * len(batch))
            params: list = []
            for observation in batch:
                params.extend(
                    [series_code, observation.reference_date, observation.value]
                )

            cur.execute(
                f"""
                INSERT INTO bcb.observations (series_code, reference_date, value)
                VALUES {placeholders}
                ON CONFLICT (series_code, reference_date) DO UPDATE
                   SET value      = EXCLUDED.value,
                       updated_at = now()
                 WHERE bcb.observations.value IS DISTINCT FROM EXCLUDED.value
                RETURNING (xmax = 0) AS was_inserted
                """,
                params,
            )

            for (was_inserted,) in cur.fetchall():
                if was_inserted:
                    inserted += 1
                else:
                    updated += 1

    return inserted, updated
