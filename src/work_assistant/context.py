"""Monta blocos de contexto (tarefas, projetos, checkpoints) para os prompts."""

import sqlite3

from work_assistant import db


def tasks_block(conn: sqlite3.Connection, day: str | None = None) -> str:
    tasks = db.list_tasks(conn, day=day)
    if not tasks:
        return "Nenhuma tarefa registrada para o dia."
    project_names = {p.id: p.name for p in db.list_projects(conn, include_done=True)}
    lines = []
    for t in tasks:
        status = "feita" if t.status == "done" else "pendente"
        prio = f", prioridade {t.priority}" if t.priority else ""
        due = ""
        if t.due_date:
            late = " ATRASADA" if t.status != "done" and t.due_date < db.today() else ""
            due = f", prazo {t.due_date}{late}"
        tags = f", tags: {t.tags}" if t.tags else ""
        project = f", projeto: {project_names[t.project_id]}" if t.project_id in project_names else ""
        lines.append(f"- [{status}{prio}{due}{tags}{project}] {t.title}")
    return "\n".join(lines)


def projects_block(conn: sqlite3.Connection) -> str:
    projects = db.list_projects(conn)
    if not projects:
        return "Nenhum projeto ativo."
    lines = []
    for p in projects:
        checkpoints = db.list_checkpoints(conn, p.id)
        last = f" (último checkpoint: {checkpoints[-1].created_at[:10]})" if checkpoints else " (sem checkpoints ainda)"
        deadline = f" [prazo: {p.deadline}]" if p.deadline else ""
        lines.append(f"- {p.name}: {p.goal}{deadline}{last}")
    return "\n".join(lines)


def latest_assessments_block(conn: sqlite3.Connection) -> str:
    """Última avaliação de checkpoint de cada projeto ativo — fonte dos impedimentos."""
    parts = []
    for p in db.list_projects(conn):
        checkpoints = db.list_checkpoints(conn, p.id)
        if checkpoints:
            last = checkpoints[-1]
            parts.append(f"- {p.name} ({last.created_at[:10]}): {last.assessment}")
    return "\n".join(parts) or "Nenhum checkpoint registrado."


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
