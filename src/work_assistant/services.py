"""Lógica de negócio compartilhada entre a CLI e a interface web.

Cada função monta o contexto, chama o modelo e persiste o resultado.
Os comandos (`commands/`) e a API web (`web/api.py`) só cuidam de
entrada/saída — nada de montagem de prompt fora daqui.
"""

import sqlite3
import urllib.error
import urllib.request
from datetime import date, timedelta

from work_assistant import config, context, db, llm

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "priority": {"type": "integer"},
                },
                "required": ["title", "priority"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["tasks"],
    "additionalProperties": False,
}

CHECKPOINT_STATUSES = ["no rumo", "em risco", "desviando"]

CHECKPOINT_SCHEMA = {
    "type": "object",
    "properties": {
        "situacao": {"type": "string"},
        "riscos": {"type": "string"},
        "proximo_passo": {"type": "array", "items": {"type": "string"}},
        "status": {"type": "string", "enum": CHECKPOINT_STATUSES},
        "resumo": {"type": "string"},
    },
    "required": ["situacao", "riscos", "proximo_passo", "status", "resumo"],
    "additionalProperties": False,
}

STANDUP_SCHEMA = {
    "type": "object",
    "properties": {
        "ontem": {"type": "string"},
        "hoje": {"type": "string"},
        "impedimentos": {"type": "string"},
    },
    "required": ["ontem", "hoje", "impedimentos"],
    "additionalProperties": False,
}


# --- Plan -------------------------------------------------------------------


def suggest_plan(conn: sqlite3.Connection, relato: str) -> list[dict]:
    """Transforma o relato do dia em uma lista de tarefas sugeridas."""
    user_message = (
        f"Tarefas já pendentes hoje:\n{context.tasks_block(conn)}\n\n"
        f"Projetos ativos:\n{context.projects_block(conn)}\n\n"
        f"Relato do usuário:\n{relato}"
    )
    result = llm.structured(llm.load_prompt("plan"), user_message, PLAN_SCHEMA)
    return sorted(result.get("tasks", []), key=lambda t: t["priority"])


def save_plan(conn: sqlite3.Connection, tasks: list[dict]) -> list[db.Task]:
    """Salva as tarefas sugeridas no to-do de hoje, ignorando títulos repetidos."""
    existing = {t.title for t in db.list_tasks(conn)}
    saved = []
    for t in tasks:
        if t["title"] in existing:
            continue
        saved.append(db.add_task(conn, t["title"], priority=t["priority"]))
        existing.add(t["title"])
    return saved


# --- Checkpoint -------------------------------------------------------------


def run_checkpoint(conn: sqlite3.Connection, project: db.Project, progress: str) -> dict:
    """Avalia o relato contra o objetivo do projeto e salva o checkpoint.

    Retorna a avaliação em blocos (para a web) e em markdown (para a CLI).
    """
    user_message = (
        f"Projeto: {project.name}\n"
        f"Objetivo da entrega: {project.goal}\n\n"
        f"Checkpoints anteriores:\n{context.checkpoints_block(conn, project.id)}\n\n"
        f"Relato de hoje:\n{progress}"
    )
    result = llm.structured(llm.load_prompt("checkpoint"), user_message, CHECKPOINT_SCHEMA)
    steps = "\n".join(f"{i}. {s}" for i, s in enumerate(result["proximo_passo"], 1))
    markdown = (
        f"**Situação**: {result['situacao']}\n\n"
        f"**Riscos e desvios**: {result['riscos']}\n\n"
        f"**Próximo passo**:\n{steps}"
    )
    db.add_checkpoint(
        conn,
        project.id,
        progress,
        markdown,
        status=result["status"],
        summary=result["resumo"],
    )
    return {
        "blocks": [
            {"title": "Situação", "body": result["situacao"]},
            {"title": "Riscos e desvios", "body": result["riscos"]},
            {"title": "Próximo passo", "body": steps},
        ],
        "markdown": markdown,
        "status": result["status"],
        "summary": result["resumo"],
    }


# --- Standup ----------------------------------------------------------------


def run_standup(conn: sqlite3.Connection, days: int = 1) -> dict:
    """Gera a fala da daily em blocos (Ontem/Hoje/Impedimentos).

    Levanta LookupError se não houver histórico no período.
    """
    start = (date.today() - timedelta(days=days)).isoformat()
    past_tasks = db.list_tasks_between(conn, start, date.today().isoformat())
    if not past_tasks:
        raise LookupError("Sem histórico no período — nada para resumir.")

    lines = []
    for t in past_tasks:
        status = "feita" if t.status == "done" else "pendente"
        lines.append(f"- {t.day} [{status}] {t.title}")

    user_message = (
        f"Hoje é {db.today()}.\n\n"
        f"Histórico de tarefas ({start} a hoje):\n" + "\n".join(lines) + "\n\n"
        f"Projetos ativos:\n{context.projects_block(conn)}\n\n"
        f"Última avaliação de checkpoint por projeto:\n{context.latest_assessments_block(conn)}"
    )
    result = llm.structured(
        llm.load_prompt("standup"), user_message, STANDUP_SCHEMA, quality=True
    )
    return {
        "blocks": [
            {"title": "Ontem", "body": result["ontem"]},
            {"title": "Hoje", "body": result["hoje"]},
            {"title": "Impedimentos", "body": result["impedimentos"]},
        ],
        "markdown": (
            f"**Ontem**: {result['ontem']}\n\n"
            f"**Hoje**: {result['hoje']}\n\n"
            f"**Impedimentos**: {result['impedimentos']}"
        ),
    }


# --- Chat -------------------------------------------------------------------


def chat_system(conn: sqlite3.Connection) -> str:
    return (
        llm.load_prompt("chat")
        + f"\n\nTarefas de hoje:\n{context.tasks_block(conn)}"
        + f"\n\nProjetos ativos:\n{context.projects_block(conn)}"
    )


def chat_reply(conn: sqlite3.Connection, message: str, history: list | None = None) -> str:
    return llm.complete(chat_system(conn), message, history=history)


# --- Servidor ---------------------------------------------------------------


def llm_online() -> bool:
    """Verifica o /health do llama.cpp sem depender do cliente OpenAI."""
    base = config.LLM_BASE_URL.removesuffix("/v1").rstrip("/")
    try:
        with urllib.request.urlopen(f"{base}/health", timeout=2) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False
