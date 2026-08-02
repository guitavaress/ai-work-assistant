"""Configuração central do assistente.

Tudo pode ser sobrescrito por variável de ambiente para facilitar
o uso em máquinas diferentes (dev e trabalho) sem editar código.
"""

import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("WA_DATA_DIR", Path.home() / ".ai-work-assistant"))
DB_PATH = DATA_DIR / "assistant.db"
MODELS_DIR = DATA_DIR / "models"

# Servidor llama.cpp (OpenAI-compatible)
# Porta 8090 no host (a 8080 costuma estar ocupada pelo Airflow); dentro do
# container o llama.cpp continua na 8080.
LLM_BASE_URL = os.environ.get("WA_LLM_BASE_URL", "http://localhost:8090/v1")
LLM_API_KEY = os.environ.get("WA_LLM_API_KEY", "sem-chave")  # llama.cpp ignora a chave
LLM_MODEL = os.environ.get("WA_LLM_MODEL", "qwen3.5-4b")

# Modelo "modo qualidade" opcional (ex.: Qwen3.5 9B inteiro na GPU em 6GB),
# servido pelo profile `quality` do docker-compose em outra porta.
# Se definido, o comando `wa review` usa este modelo.
QUALITY_MODEL = os.environ.get("WA_QUALITY_MODEL", "")
QUALITY_BASE_URL = os.environ.get("WA_QUALITY_BASE_URL", "http://localhost:8091/v1")

LLM_TIMEOUT_SECONDS = float(os.environ.get("WA_LLM_TIMEOUT", "120"))

# O Qwen3.5 é um modelo "thinking": por padrão raciocina longamente antes de
# responder, o que estoura o orçamento de tokens e trava a saída estruturada.
# Desabilitado por padrão; WA_ENABLE_THINKING=1 reativa (só afeta texto livre —
# a saída estruturada sempre roda sem thinking).
ENABLE_THINKING = os.environ.get("WA_ENABLE_THINKING", "") == "1"

# No caminho de qualidade (9B), thinking vem ligado por padrão: o modelo é
# capaz e o ganho de raciocínio compensa. Só afeta texto livre (hoje, `wa review`);
# a saída estruturada continua sempre sem thinking. WA_QUALITY_ENABLE_THINKING=0 desliga.
QUALITY_ENABLE_THINKING = os.environ.get("WA_QUALITY_ENABLE_THINKING", "1") == "1"

MAX_TOKENS = int(os.environ.get("WA_MAX_TOKENS", "2048"))

# Com thinking ligado o modelo gasta tokens raciocinando antes da resposta;
# o caminho de qualidade usa um teto maior para não truncar a resposta final.
QUALITY_MAX_TOKENS = int(os.environ.get("WA_QUALITY_MAX_TOKENS", "4096"))

# Interface web local (`wa web`)
WEB_HOST = os.environ.get("WA_WEB_HOST", "127.0.0.1")
WEB_PORT = int(os.environ.get("WA_WEB_PORT", "8765"))

# Nome usado na saudação da interface web (vazio = saudação sem nome)
USER_NAME = os.environ.get("WA_USER_NAME", "")


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
