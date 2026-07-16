"""Monta blocos de contexto (tarefas, projetos, checkpoints) para os prompts."""

import sqlite3

from work_assistant import db


def tasks_block(conn: sqlite3.Connection, day: str | None = None) -> str:
    tasks = db.list_tasks(conn, day=day)
    if not tasks:
        return "Nenhuma tarefa registrada para o dia."
    lines = []
    for t in tasks:
        status = "feita" if t.status == "done" else "pendente"
        prio = f", prioridade {t.priority}" if t.priority else ""
        lines.append(f"- [{status}{prio}] {t.title}")
    return "\n".join(lines)


def projects_block(conn: sqlite3.Connection) -> str:
    projects = db.list_projects(conn)
    if not projects:
        return "Nenhum projeto ativo."
    lines = []
    for p in projects:
        checkpoints = db.list_checkpoints(conn, p.id)
        last = f" (último checkpoint: {checkpoints[-1].created_at[:10]})" if checkpoints else " (sem checkpoints ainda)"
        lines.append(f"- {p.name}: {p.goal}{last}")
    return "\n".join(lines)


def checkpoints_block(conn: sqlite3.Connection, project_id: int, limit: int = 3) -> str:
    checkpoints = db.list_checkpoints(conn, project_id)[-limit:]
    if not checkpoints:
        return "Nenhum checkpoint anterior — este é o primeiro."
    parts = []
    for c in checkpoints:
        parts.append(
            f"[{c.created_at[:10]}]\nRelato: {c.progress}\nAvaliação: {c.assessment}"
        )
    return "\n\n".join(parts)
