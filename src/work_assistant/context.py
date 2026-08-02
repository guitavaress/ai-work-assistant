"""Monta blocos de contexto (tarefas, projetos, checkpoints) para os prompts."""

import sqlite3

from work_assistant import db


def tasks_block(conn: sqlite3.Connection, day: str | None = None) -> str:
    tasks = db.list_tasks(conn, day=day)
    if not tasks:
        return "Nenhuma tarefa registrada para o dia."
    project_names = {
        p.id: p.name for p in db.list_projects(conn, include_done=True, kind=None)
    }
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


def stages_block(
    conn: sqlite3.Connection, project_id: int, stage_id: int | None = None
) -> str:
    """Etapas do projeto com prazo, critério de pronto e tarefas pendentes.

    `stage_id` marca com `>>>` a etapa em foco no checkpoint.
    """
    stages = db.list_stages(conn, project_id)
    if not stages:
        return "Este projeto não tem etapas definidas."
    today = db.today()
    lines = []
    for s in stages:
        status = "feita" if s.status == "done" else "pendente"
        due = ""
        if s.deadline:
            late = " ATRASADA" if s.status != "done" and s.deadline < today else ""
            due = f" — prazo {s.deadline}{late}"
        focus = ">>> " if s.id == stage_id else ""
        lines.append(f"{focus}{s.position}. [{status}] {s.name}{due}")
        if s.done_criteria:
            lines.append(f"   pronto quando: {s.done_criteria}")
        pending = [t.title for t in db.list_tasks_by_stage(conn, s.id, include_done=False)]
        if pending:
            lines.append(f"   pendentes: {'; '.join(pending)}")
    return "\n".join(lines)


def routine_runs_block(conn: sqlite3.Connection) -> str:
    """Ciclos de rotina abertos, com prazo e quanto já fechou."""
    runs = db.list_projects(conn, kind="routine_run")
    if not runs:
        return "Nenhuma rotina em andamento."
    today = db.today()
    lines = []
    for run in runs:
        stages = db.list_stages(conn, run.id)
        done = sum(1 for s in stages if s.status == "done")
        deadline = ""
        if run.deadline:
            late = " ATRASADO" if run.deadline < today else ""
            deadline = f" [prazo: {run.deadline}{late}]"
        pending = [s.name for s in stages if s.status != "done"]
        falta = f" — falta: {', '.join(pending)}" if pending else " — todas as etapas fechadas"
        lines.append(f"- {run.name}{deadline}: {done}/{len(stages)} etapas{falta}")
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
