"""Cliente para o servidor llama.cpp (API OpenAI-compatible).

O servidor sobe via `docker compose -f docker/docker-compose.yml up` e expõe
http://localhost:8090/v1. A saída estruturada usa `json_schema`, que o
llama.cpp converte em gramática GBNF — garante JSON válido mesmo em modelos
pequenos como o Qwen3.5 4B.
"""

import json
from importlib import resources

from openai import OpenAI

from work_assistant import config


def client(base_url: str | None = None) -> OpenAI:
    return OpenAI(
        base_url=base_url or config.LLM_BASE_URL,
        api_key=config.LLM_API_KEY,
        timeout=config.LLM_TIMEOUT_SECONDS,
    )


def load_prompt(name: str) -> str:
    return resources.files("work_assistant.prompts").joinpath(f"{name}.md").read_text()


def complete(
    system: str, user: str, history: list | None = None, quality: bool = False
) -> str:
    """Chat simples: retorna o texto da resposta.

    Com quality=True e WA_QUALITY_MODEL definido, usa o servidor do modelo
    de qualidade (porta 8091 no docker-compose) em vez do padrão, com thinking
    ligado (WA_QUALITY_ENABLE_THINKING) e teto de tokens maior (QUALITY_MAX_TOKENS).
    """
    if quality and config.QUALITY_MODEL:
        api, model = client(config.QUALITY_BASE_URL), config.QUALITY_MODEL
        thinking, max_tokens = config.QUALITY_ENABLE_THINKING, config.QUALITY_MAX_TOKENS
    else:
        api, model = client(), config.LLM_MODEL
        thinking, max_tokens = config.ENABLE_THINKING, config.MAX_TOKENS
    messages = [{"role": "system", "content": system}]
    messages.extend(history or [])
    messages.append({"role": "user", "content": user})
    response = api.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.7,
        max_tokens=max_tokens,
        extra_body={"chat_template_kwargs": {"enable_thinking": thinking}},
    )
    return response.choices[0].message.content or ""


def structured(
    system: str, user: str, schema: dict, model: str | None = None, quality: bool = False
) -> dict:
    """Chat com saída JSON garantida pelo schema (gramática no llama.cpp).

    Thinking sempre desligado aqui: com ele ativo o modelo gasta o orçamento
    de tokens raciocinando e devolve o JSON vazio.
    """
    if quality and config.QUALITY_MODEL:
        api, default_model = client(config.QUALITY_BASE_URL), config.QUALITY_MODEL
    else:
        api, default_model = client(), config.LLM_MODEL
    response = api.chat.completions.create(
        model=model or default_model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.3,
        max_tokens=config.MAX_TOKENS,
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "resposta", "schema": schema, "strict": True},
        },
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
    return json.loads(response.choices[0].message.content or "{}")
