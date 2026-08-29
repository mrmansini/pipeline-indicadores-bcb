"""
Configuração do pipeline.

Lê as variáveis do arquivo .env e falha cedo se algo obrigatório estiver
faltando. Erro de configuração deve estourar na inicialização, não no meio
de uma carga.
"""

import os
from datetime import date

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL não definida. Copie o .env.example para .env e preencha."
    )

# Timeout de rede por requisição, em segundos.
BCB_TIMEOUT = int(os.getenv("BCB_TIMEOUT", "30"))

# Quantas vezes tentar de novo antes de desistir de uma janela.
BCB_MAX_RETRIES = int(os.getenv("BCB_MAX_RETRIES", "3"))

# Data inicial usada quando a série ainda não tem nenhuma observação no banco.
DEFAULT_START_DATE = date(2015, 1, 1)

# Tamanho da janela de coleta, em anos, por periodicidade da série.
#
# O SGS recusa respostas grandes demais: devolve 200 com uma página HTML de
# "Requisição inválida" em vez de um erro honesto. O limite é de volume, não
# de tempo — uma série diária estoura em 2 anos, uma mensal atravessa 5 sem
# problema. Por isso a janela vem do catálogo, não de uma constante única.
WINDOW_YEARS_BY_FREQUENCY = {
    "daily": 1,
    "monthly": 5,
}
DEFAULT_WINDOW_YEARS = 1  # conservador: na dúvida sobre a periodicidade, janela curta

# Quantas observações vão em cada INSERT.
BATCH_SIZE = 500
