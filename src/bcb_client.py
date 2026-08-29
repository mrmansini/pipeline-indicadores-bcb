"""
Cliente da API de séries temporais do Banco Central (SGS).

Responsabilidades:
  - montar a requisição no formato que a API espera;
  - quebrar intervalos longos em janelas, porque a API rejeita períodos
    muito extensos em séries diárias;
  - tentar de novo em falha transitória, com espera crescente;
  - devolver dado já convertido para tipo Python, não string.

A regra que separa este módulo do resto: aqui não existe banco de dados.
Ele busca e converte; quem persiste é outro.
"""

import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

import requests

from config import (
    BCB_MAX_RETRIES,
    BCB_TIMEOUT,
    DEFAULT_WINDOW_YEARS,
    WINDOW_YEARS_BY_FREQUENCY,
)

logger = logging.getLogger(__name__)

BASE_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados"

# Status que valem uma nova tentativa: excesso de requisições e erro do
# servidor. Um 400 ou 404 não adianta repetir — o problema é o pedido.
RETRYABLE_STATUS = {429, 500, 502, 503, 504}

# O SGS recusa o User-Agent padrão do requests em consultas por período:
# responde 200 com uma página HTML de "Requisição inválida", em vez de um
# 403 honesto. Identificar-se como navegador é o que faz a consulta passar.
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; pipeline-indicadores-bcb/1.0)",
    "Accept": "application/json",
}

# Pausa entre janelas consecutivas, em segundos.
DELAY_BETWEEN_WINDOWS = 1.0

# Teto da espera entre tentativas, para o backoff exponencial não explodir.
MAX_BACKOFF_SECONDS = 30


class InvalidResponseError(RuntimeError):
    """
    A API respondeu, mas com algo que não é a série pedida.

    O SGS falha de forma intermitente: a mesma requisição devolve JSON numa
    hora e uma página HTML de "Requisição inválida" na outra, sempre com
    status 200. Como a falha não é determinística, ela é tratada como
    transitória e entra no ciclo de novas tentativas.
    """


@dataclass(frozen=True)
class Observation:
    """Uma observação de uma série: uma data e um valor."""

    reference_date: date
    value: Decimal | None


def _build_url(series_code: int, start: date, end: date) -> str:
    """
    Monta a URL com as datas embutidas, sem passar por `params`.

    O SGS exige a barra literal em dd/mm/aaaa. Se as datas forem passadas
    pelo parâmetro `params` do requests, as barras viram %2F e a API
    responde 200 com uma página HTML de "Requisição inválida" — o que
    quebra o parse do JSON de um jeito bem pouco óbvio de diagnosticar.

    Junto com o User-Agent em HEADERS, são as duas condições necessárias
    para a consulta por período funcionar. Uma sem a outra ainda devolve
    a página de erro.
    """
    return (
        f"{BASE_URL.format(code=series_code)}"
        f"?formato=json"
        f"&dataInicial={start.strftime('%d/%m/%Y')}"
        f"&dataFinal={end.strftime('%d/%m/%Y')}"
    )


def _date_windows(start: date, end: date, max_years: int):
    """Divide o intervalo em janelas de no máximo `max_years` anos."""
    current = start
    while current <= end:
        window_end = min(
            date(current.year + max_years, current.month, current.day) - timedelta(days=1),
            end,
        )
        yield current, window_end
        current = window_end + timedelta(days=1)


def _parse_row(row: dict) -> Observation | None:
    """
    Converte uma linha crua da API em Observation.

    Linha malformada vira aviso e é descartada, em vez de derrubar a carga
    inteira: uma observação estranha não deve custar as outras cinco mil.
    """
    try:
        reference_date = datetime.strptime(row["data"], "%d/%m/%Y").date()
    except (KeyError, TypeError, ValueError):
        logger.warning("Linha descartada, data inválida: %r", row)
        return None

    raw_value = (row.get("valor") or "").strip()
    if not raw_value:
        return Observation(reference_date, None)

    try:
        return Observation(reference_date, Decimal(raw_value))
    except InvalidOperation:
        logger.warning("Linha descartada, valor inválido: %r", row)
        return None


def _read_payload(response: requests.Response, series_code: int) -> list[dict]:
    """
    Extrai a lista de observações da resposta, validando o que veio.

    O SGS responde 200 mesmo quando não entende o pedido, devolvendo HTML.
    Confiar no status seria aceitar uma página de erro como se fosse dado.
    """
    body = response.text.strip()
    if not body:
        return []

    content_type = response.headers.get("content-type", "")
    if "json" not in content_type.lower():
        raise InvalidResponseError(
            f"Série {series_code}: a API respondeu {response.status_code} com "
            f"content-type '{content_type}' em vez de JSON. "
            f"Início da resposta: {body[:120]!r}"
        )

    payload = response.json()
    if not isinstance(payload, list):
        raise InvalidResponseError(
            f"Série {series_code}: esperava uma lista, veio {type(payload).__name__}."
        )

    return payload


def _request_window(series_code: int, start: date, end: date) -> list[dict]:
    """Busca uma janela, com novas tentativas apenas em falha transitória."""
    url = _build_url(series_code, start, end)
    last_error: Exception | None = None

    for attempt in range(1, BCB_MAX_RETRIES + 1):
        try:
            response = requests.get(url, timeout=BCB_TIMEOUT, headers=HEADERS)

            # A API responde 404 quando não há dado no período. Isso não é
            # erro: é resposta vazia.
            if response.status_code == 404:
                logger.info(
                    "Série %s sem dados entre %s e %s.", series_code, start, end
                )
                return []

            if response.status_code in RETRYABLE_STATUS:
                raise requests.HTTPError(
                    f"HTTP {response.status_code} (transitório)", response=response
                )

            response.raise_for_status()
            return _read_payload(response, series_code)

        except (requests.RequestException, InvalidResponseError, ValueError) as error:
            # Falha de rede, erro transitório do servidor ou resposta que não
            # é a série pedida. Todos entram no mesmo ciclo de tentativas,
            # porque no SGS os três são intermitentes.
            last_error = error
            if attempt == BCB_MAX_RETRIES:
                break
            wait = min(2 ** attempt, MAX_BACKOFF_SECONDS)
            logger.warning(
                "Tentativa %s/%s falhou para a série %s (%s). Nova tentativa em %ss.",
                attempt, BCB_MAX_RETRIES, series_code, error, wait,
            )
            time.sleep(wait)

    raise RuntimeError(
        f"Falha ao buscar a série {series_code} entre {start} e {end} "
        f"após {BCB_MAX_RETRIES} tentativas: {last_error}"
    ) from last_error


def window_years_for(frequency: str | None) -> int:
    """
    Tamanho da janela de coleta, em anos, para a periodicidade informada.

    Periodicidade desconhecida cai no valor conservador: melhor fazer
    requisições a mais do que estourar o limite da API em silêncio.
    """
    return WINDOW_YEARS_BY_FREQUENCY.get(frequency or "", DEFAULT_WINDOW_YEARS)


def iter_series_windows(
    series_code: int,
    start: date,
    end: date,
    frequency: str | None = None,
) -> Iterator[tuple[date, date, list[Observation]]]:
    """
    Percorre o intervalo janela a janela, entregando cada uma assim que chega.

    Devolver um gerador, em vez de acumular tudo e retornar no fim, é o que
    permite a quem chama gravar o progresso a cada janela. Numa coleta de 12
    janelas, a falha da nona não pode custar as oito que já vieram.

    As janelas saem em ordem cronológica, e a exceção interrompe a iteração.
    Isso mantém o histórico gravado sempre contíguo: a carga para no buraco,
    em vez de pular por cima dele e deixar uma lacuna que a carga incremental
    nunca mais voltaria para preencher.
    """
    max_years = window_years_for(frequency)

    for index, (window_start, window_end) in enumerate(
        _date_windows(start, end, max_years)
    ):
        # Pausa curta entre janelas: evita disparar requisições em rajada
        # contra uma API pública.
        if index > 0:
            time.sleep(DELAY_BETWEEN_WINDOWS)

        logger.info(
            "Buscando série %s de %s até %s.", series_code, window_start, window_end
        )

        observations = []
        for row in _request_window(series_code, window_start, window_end):
            observation = _parse_row(row)
            if observation is not None:
                observations.append(observation)

        yield window_start, window_end, observations
