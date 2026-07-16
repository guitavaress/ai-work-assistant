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
LLM_BASE_URL = os.environ.get("WA_LLM_BASE_URL", "http://localhost:8080/v1")
LLM_API_KEY = os.environ.get("WA_LLM_API_KEY", "sem-chave")  # llama.cpp ignora a chave
LLM_MODEL = os.environ.get("WA_LLM_MODEL", "qwen3.5-4b")

# Modelo "modo qualidade" opcional (ex.: Qwen3.5 9B com offload parcial),
# servido pelo profile `quality` do docker-compose em outra porta.
# Se definido, o comando `wa standup` usa este modelo.
QUALITY_MODEL = os.environ.get("WA_QUALITY_MODEL", "")
QUALITY_BASE_URL = os.environ.get("WA_QUALITY_BASE_URL", "http://localhost:8081/v1")

LLM_TIMEOUT_SECONDS = float(os.environ.get("WA_LLM_TIMEOUT", "120"))


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
