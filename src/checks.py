"""
Validações de qualidade sobre o que foi carregado.

O pipeline responde "a carga rodou?". Este módulo responde a pergunta que
importa de verdade: "dá para confiar no que está no banco?".

A distinção não é acadêmica. Na construção deste projeto, a série 3698 foi
carregada sem nenhum erro, reportou sucesso e trouxe o dado errado — o
catálogo dizia diária, mas a série é mensal. Nenhuma verificação de execução
pegaria isso; só a conferência do dado pega.

Uso:
    python src/checks.py

Código de saída: 0 quando não há erro, 1 quando há. Isso é o que permite
usar este módulo como portão em uma automação — carga que não passa na
validação não deveria seguir para o dashboard.
"""

import logging
import sys
from dataclasses import dataclass
from datetime import date

import db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("checks")

# Limite padrão de defasagem, em dias, por periodicidade. Vale apenas quando
# a série não define o seu próprio `max_lag_days` no catálogo — o calendário
# de divulgação varia demais entre indicadores para um número só servir.
MAX_LAG_DAYS = {"daily": 10, "monthly": 75}
DEFAULT_MAX_LAG_DAYS = 75

# Intervalo mediano esperado entre observações, em dias. Serve para conferir
# se a periodicidade declarada no catálogo bate com o dado observado.
EXPECTED_MEDIAN_INTERVAL = {
    "daily": (1, 5),      # dia útil: 1 dia na semana, até 4 em feriado prolongado
    "monthly": (28, 31),
}

# Acima disso, a distância entre duas observações consecutivas deixa de ser
# fim de semana ou feriado e passa a ser lacuna de verdade.
MAX_DAILY_GAP_DAYS = 10


@dataclass
class Finding:
    """Um achado da validação."""

    level: str  # 'ERROR' ou 'WARNING'
    series_code: int | None
    message: str


def check_empty_series(conn) -> list[Finding]:
    """Série ativa no catálogo que não tem nenhuma observação."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT s.series_code, s.name
              FROM bcb.series s
              LEFT JOIN bcb.observations o USING (series_code)
             WHERE s.is_active
             GROUP BY s.series_code, s.name
            HAVING count(o.*) = 0
             ORDER BY s.series_code
            """
        )
        return [
            Finding("ERROR", code, f"{name}: série ativa sem nenhuma observação.")
            for code, name in cur.fetchall()
        ]


def check_null_values(conn) -> list[Finding]:
    """Percentual de observações sem valor."""
    findings: list[Finding] = []
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT series_code,
                   count(*)                                   AS total,
                   count(*) FILTER (WHERE value IS NULL)      AS nulos
              FROM bcb.observations
             GROUP BY series_code
             ORDER BY series_code
            """
        )
        for series_code, total, nulos in cur.fetchall():
            if not nulos:
                continue
            pct = 100 * nulos / total
            level = "ERROR" if pct > 5 else "WARNING"
            findings.append(
                Finding(
                    level, series_code,
                    f"{nulos} de {total} observações sem valor ({pct:.1f}%).",
                )
            )
    return findings


def check_declared_frequency(conn) -> list[Finding]:
    """
    Confere se a periodicidade declarada bate com o intervalo observado.

    Esta é a verificação que teria pego o erro da série 3698 no dia em que
    ele foi cometido, em vez de horas depois, por acaso, ao conferir uma
    contagem na mão.
    """
    findings: list[Finding] = []
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT s.series_code,
                   s.frequency,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY d.gap_days) AS mediana
              FROM (
                   SELECT series_code,
                          reference_date - lag(reference_date)
                              OVER (PARTITION BY series_code ORDER BY reference_date)
                              AS gap_days
                     FROM bcb.observations
                   ) d
              JOIN bcb.series s USING (series_code)
             WHERE d.gap_days IS NOT NULL
             GROUP BY s.series_code, s.frequency
             ORDER BY s.series_code
            """
        )
        for series_code, frequency, mediana in cur.fetchall():
            expected = EXPECTED_MEDIAN_INTERVAL.get(frequency)
            if expected is None:
                findings.append(
                    Finding(
                        "WARNING", series_code,
                        f"periodicidade '{frequency}' não é conhecida pela validação.",
                    )
                )
                continue

            low, high = expected
            if not low <= mediana <= high:
                findings.append(
                    Finding(
                        "ERROR", series_code,
                        f"catálogo diz '{frequency}', mas o intervalo mediano "
                        f"observado é de {mediana:.0f} dias.",
                    )
                )
    return findings


def check_gaps(conn) -> list[Finding]:
    """
    Lacunas no histórico.

    Mensal: compara o total observado com o número de meses entre a primeira
    e a última observação. Diária: procura saltos maiores que um feriado
    prolongado explicaria.
    """
    findings: list[Finding] = []

    with conn.cursor() as cur:
        # Séries mensais: quantos meses deveriam existir versus quantos existem.
        cur.execute(
            """
            SELECT s.series_code,
                   count(*)                                                  AS total,
                   1 + (EXTRACT(YEAR  FROM age(max(o.reference_date), min(o.reference_date))) * 12
                      + EXTRACT(MONTH FROM age(max(o.reference_date), min(o.reference_date))))
                                                                             AS esperado
              FROM bcb.observations o
              JOIN bcb.series s USING (series_code)
             WHERE s.frequency = 'monthly'
             GROUP BY s.series_code
             ORDER BY s.series_code
            """
        )
        for series_code, total, esperado in cur.fetchall():
            faltando = int(esperado) - total
            if faltando > 0:
                findings.append(
                    Finding(
                        "ERROR", series_code,
                        f"{faltando} mês(es) faltando: {total} observações para "
                        f"{int(esperado)} meses de histórico.",
                    )
                )

        # Séries diárias: saltos longos demais entre observações consecutivas.
        cur.execute(
            """
            SELECT series_code, count(*), max(gap_days)
              FROM (
                   SELECT o.series_code,
                          o.reference_date - lag(o.reference_date)
                              OVER (PARTITION BY o.series_code ORDER BY o.reference_date)
                              AS gap_days
                     FROM bcb.observations o
                     JOIN bcb.series s USING (series_code)
                    WHERE s.frequency = 'daily'
                   ) d
             WHERE gap_days > %s
             GROUP BY series_code
             ORDER BY series_code
            """,
            (MAX_DAILY_GAP_DAYS,),
        )
        for series_code, quantidade, maior in cur.fetchall():
            findings.append(
                Finding(
                    "WARNING", series_code,
                    f"{quantidade} lacuna(s) acima de {MAX_DAILY_GAP_DAYS} dias; "
                    f"a maior é de {maior} dias.",
                )
            )

    return findings


def check_freshness(conn) -> list[Finding]:
    """
    Defasagem entre a última observação e hoje.

    O limite vem do catálogo quando a série define o seu, porque o calendário
    de divulgação é atributo do indicador: o IPCA sai poucos dias depois do
    mês fechar, o IBC-Br leva mais de dois meses. Um limite único para tudo
    que é mensal produziria alarme falso permanente no IBC-Br.
    """
    findings: list[Finding] = []
    today = date.today()

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT s.series_code, s.frequency, s.max_lag_days, max(o.reference_date)
              FROM bcb.observations o
              JOIN bcb.series s USING (series_code)
             WHERE s.is_active
             GROUP BY s.series_code, s.frequency, s.max_lag_days
             ORDER BY s.series_code
            """
        )
        for series_code, frequency, max_lag_days, ultima in cur.fetchall():
            lag = (today - ultima).days
            limite = max_lag_days or MAX_LAG_DAYS.get(frequency, DEFAULT_MAX_LAG_DAYS)
            if lag > limite:
                findings.append(
                    Finding(
                        "WARNING", series_code,
                        f"última observação em {ultima} ({lag} dias atrás; "
                        f"esperado até {limite}).",
                    )
                )
    return findings


def check_failed_runs(conn) -> list[Finding]:
    """
    Falhas que ainda não foram superadas.

    Só interessa a falha sem sucesso posterior para a mesma série. Avisar
    sobre erro que o pipeline já resolveu sozinho na execução seguinte é a
    receita para o time aprender a ignorar o alerta — e alerta ignorado é
    pior do que alerta nenhum, porque dá sensação de cobertura.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT r.series_code, count(*), max(r.error_message)
              FROM bcb.runs r
             WHERE r.status = 'FAILED'
               AND r.started_at > now() - interval '24 hours'
               AND NOT EXISTS (
                   SELECT 1
                     FROM bcb.runs posterior
                    WHERE posterior.series_code = r.series_code
                      AND posterior.status      = 'SUCCESS'
                      AND posterior.started_at  > r.started_at
                   )
             GROUP BY r.series_code
             ORDER BY r.series_code
            """
        )
        return [
            Finding(
                "ERROR", series_code,
                f"{quantidade} falha(s) sem sucesso posterior nas últimas 24h. "
                f"Último erro: {(erro or '')[:120]}",
            )
            for series_code, quantidade, erro in cur.fetchall()
        ]


CHECKS = (
    ("Séries sem dado",        check_empty_series),
    ("Valores nulos",          check_null_values),
    ("Periodicidade x dado",   check_declared_frequency),
    ("Lacunas no histórico",   check_gaps),
    ("Defasagem",              check_freshness),
    ("Falhas não superadas",   check_failed_runs),
)


def main() -> int:
    findings: list[Finding] = []

    with db.connect() as conn:
        for label, check in CHECKS:
            resultado = check(conn)
            status = "OK" if not resultado else f"{len(resultado)} achado(s)"
            logger.info("%-24s %s", label, status)
            findings.extend(resultado)

    errors = [f for f in findings if f.level == "ERROR"]
    warnings = [f for f in findings if f.level == "WARNING"]

    if findings:
        print()
        for finding in findings:
            prefixo = f"[{finding.series_code}]" if finding.series_code else "[geral]"
            print(f"  {finding.level:<8} {prefixo:<9} {finding.message}")
        print()

    logger.info("Validação concluída: %s erro(s), %s aviso(s).", len(errors), len(warnings))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
