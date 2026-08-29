"""
Orquestração da carga.

Para cada série ativa: descobre de quando retomar, busca na API, grava e
registra a execução. A falha de uma série não interrompe as outras.

Uso:
    python src/pipeline.py                 # carga incremental de todas as séries
    python src/pipeline.py --full          # recarrega tudo desde a data inicial
    python src/pipeline.py --series 433    # apenas uma série
"""

import argparse
import logging
import sys
from datetime import date, timedelta

import db
from bcb_client import iter_series_windows
from config import DEFAULT_START_DATE

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("pipeline")

# Quantos dias antes da última observação recarregar. Índice econômico é
# revisado depois de publicado, então retomar exatamente de onde parou faz o
# pipeline nunca enxergar a revisão.
OVERLAP_DAYS = 30


def resolve_start_date(conn, series_code: int, full_reload: bool) -> date:
    """Decide a partir de quando buscar."""
    if full_reload:
        return DEFAULT_START_DATE

    last = db.get_last_reference_date(conn, series_code)
    if last is None:
        return DEFAULT_START_DATE

    return max(last - timedelta(days=OVERLAP_DAYS), DEFAULT_START_DATE)


def run_series(
    conn, series_code: int, name: str, frequency: str | None, full_reload: bool
) -> bool:
    """
    Processa uma série, gravando a cada janela. Devolve True em caso de sucesso.

    O commit por janela é o que faz a coleta ser retomável: se a nona janela
    falhar, as oito anteriores já estão no banco, e a próxima execução
    retoma exatamente de onde parou, porque a data inicial é calculada a
    partir da última observação armazenada.
    """
    start = resolve_start_date(conn, series_code, full_reload)
    end = date.today()

    run_id = db.start_run(conn, series_code, start, end)
    conn.commit()  # o log existe antes do trabalho, para sobreviver a uma falha

    received = inserted = updated = 0

    try:
        for window_start, window_end, observations in iter_series_windows(
            series_code, start, end, frequency
        ):
            received += len(observations)

            if observations:
                window_inserted, window_updated = db.upsert_observations(
                    conn, series_code, observations
                )
                inserted += window_inserted
                updated += window_updated

            # Progresso preservado janela a janela.
            conn.commit()

        status = "SUCCESS" if received else "NO_DATA"
        db.finish_run(
            conn, run_id, status,
            received=received, inserted=inserted, updated=updated,
        )
        conn.commit()

        logger.info(
            "[%s] %s — %s recebidas, %s inseridas, %s atualizadas.",
            series_code, name, received, inserted, updated,
        )
        return True

    except Exception as error:  # noqa: BLE001 — falha de uma série não derruba as outras
        conn.rollback()
        db.finish_run(
            conn, run_id, "FAILED",
            received=received, inserted=inserted, updated=updated,
            error_message=str(error),
        )
        conn.commit()
        logger.error(
            "[%s] %s — interrompida após %s observações gravadas: %s",
            series_code, name, inserted + updated, error,
        )
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Carga de indicadores do BCB.")
    parser.add_argument(
        "--full", action="store_true",
        help="recarrega desde a data inicial em vez de carga incremental",
    )
    parser.add_argument(
        "--series", type=int, default=None,
        help="processa apenas o código de série informado",
    )
    args = parser.parse_args()

    with db.connect() as conn:
        series = db.list_active_series(conn)

        if args.series is not None:
            series = [s for s in series if s[0] == args.series]
            if not series:
                logger.error("Série %s não encontrada ou inativa.", args.series)
                return 1

        logger.info("Iniciando carga de %s série(s).", len(series))

        failures = 0
        for series_code, name, frequency in series:
            if not run_series(conn, series_code, name, frequency, args.full):
                failures += 1

    if failures:
        logger.error("Carga concluída com %s falha(s).", failures)
        return 1

    logger.info("Carga concluída com sucesso.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
