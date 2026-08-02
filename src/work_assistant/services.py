"""Lógica de negócio compartilhada entre a CLI e a interface web.

Cada função monta o contexto, chama o modelo e persiste o resultado.
Os comandos (`commands/`) e a API web (`web/api.py`) só cuidam de
entrada/saída — nada de montagem de prompt fora daqui.
"""

import sqlite3
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta

from work_assistant import config, context, db, llm, schedule

# Teto de segurança do backfill: uma rotina parada há meses não deve gerar
# dezenas de ciclos no primeiro comando (o piso real é o created_at da rotina).
ROUTINE_LOOKBACK_DAYS = 92

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
                    "due_date": {"type": "string"},  # YYYY-MM-DD; "" = sem prazo
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "effort": {"type": "string", "enum": list(db.EFFORT_LEVELS)},
                },
                "required": ["title", "priority", "due_date", "tags", "effort"],
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
        # O modelo identifica a etapa pelo NOME (que ele recebe no contexto), nunca
        # por id: pedir id a um LLM é convite para alucinação com chave estrangeira.
        "vereditos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "etapa": {"type": "string"},
                    "veredito": {"type": "string", "enum": list(db.VERDICT_VALUES)},
                    "justificativa": {"type": "string"},
                },
                "required": ["etapa", "veredito", "justificativa"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["situacao", "riscos", "proximo_passo", "status", "resumo", "vereditos"],
    "additionalProperties": False,
}

# --- Plan -------------------------------------------------------------------


def suggest_plan(conn: sqlite3.Connection, relato: str) -> list[dict]:
    """Transforma o relato do dia em uma lista de tarefas sugeridas."""
    known_tags = db.list_known_tags(conn)
    tags_line = ", ".join(known_tags) if known_tags else "nenhuma ainda"
    user_message = (
        f"Hoje é {db.today()}.\n\n"
        f"Tarefas já pendentes hoje:\n{context.tasks_block(conn)}\n\n"
        f"Projetos ativos:\n{context.projects_block(conn)}\n\n"
        f"Rotinas em andamento:\n{context.routine_runs_block(conn)}\n\n"
        f"Tags já usadas: {tags_line}\n\n"
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
        saved.append(
            db.add_task(
                conn,
                t["title"],
                priority=t["priority"],
                due_date=t.get("due_date") or None,
                tags=t.get("tags") or None,
                effort=t.get("effort") or None,
                source="plan",
            )
        )
        existing.add(t["title"])
    return saved


# --- Rotinas ----------------------------------------------------------------


def materialize_run(
    conn: sqlite3.Connection, routine: db.Routine, period: str
) -> db.Project:
    """Cria o ciclo do período (ou devolve o existente) com as etapas do checklist.

    As etapas são CÓPIA do checklist da rotina, não referência: o ciclo é o registro
    do que se pediu naquele período, e editar a rotina depois não reescreve o passado.
    """
    existing = db.find_routine_run(conn, routine.id, period)
    if existing is not None:
        return existing

    opening = schedule.opens_on(routine.cadence, routine.anchor, period)
    deadline = schedule.closes_on(
        routine.cadence, routine.anchor, routine.sla_days, period
    )
    name = f"{routine.name} — {period}"
    try:
        run = db.add_routine_run(
            conn, routine.id, period, name, routine.goal, deadline.isoformat()
        )
    except sqlite3.IntegrityError:
        # Ou outra sessão (web/CLI) materializou o mesmo ciclo, ou o nome colidiu
        # com um projeto que o usuário criou na mão.
        concurrent = db.find_routine_run(conn, routine.id, period)
        if concurrent is not None:
            return concurrent
        run = db.add_routine_run(
            conn, routine.id, period, f"{name} (#{routine.id})", routine.goal, deadline.isoformat()
        )

    for step in db.list_routine_steps(conn, routine.id):
        db.add_stage(
            conn,
            run.id,
            step.name,
            deadline=(opening + timedelta(days=step.offset_days)).isoformat(),
            done_criteria=step.done_criteria,
            position=step.position,
        )
    return run


def ensure_routines(
    conn: sqlite3.Connection, today: str | None = None
) -> list[db.Project]:
    """Materializa os ciclos cuja janela já abriu. Idempotente.

    Chamada pelos comandos que leem o dia (to-do, plan, web) — sem daemon nem cron.
    Devolve só os ciclos criados agora, para quem quiser avisar o usuário.
    """
    routines = db.list_routines(conn)
    if not routines:
        return []

    now = date.fromisoformat(today or db.today())
    floor = now - timedelta(days=ROUTINE_LOOKBACK_DAYS)
    created = []
    for routine in routines:
        start = max(date.fromisoformat(routine.created_at[:10]), floor)
        for period in schedule.periods_between(
            routine.cadence, routine.anchor, start, now
        ):
            if db.find_routine_run(conn, routine.id, period) is None:
                created.append(materialize_run(conn, routine, period))
    return created


def close_routine_run(
    conn: sqlite3.Connection, project: db.Project, closed_on: str | None = None
) -> db.Project:
    """Fecha o ciclo. Sempre manual: ver a janela do mês passado aberta é o sinal."""
    return db.complete_project(conn, project.id, closed_on=closed_on)


def routine_view(conn: sqlite3.Connection, routine: db.Routine) -> dict:
    """Rotina + checklist + ciclos com progresso + próxima abertura (para `wa routine show`)."""
    runs = []
    for run in db.list_routine_runs(conn, routine.id):
        stages = db.list_stages(conn, run.id)
        runs.append(
            {
                "project": run,
                "tasks": db.project_progress(conn, run.id),
                "stages": {
                    "total": len(stages),
                    "done": sum(1 for s in stages if s.status == "done"),
                },
            }
        )
    return {
        "routine": routine,
        "cadence": schedule.describe(routine.cadence, routine.anchor, routine.sla_days),
        "steps": db.list_routine_steps(conn, routine.id),
        "runs": runs,
        "next_open": schedule.next_open(
            routine.cadence, routine.anchor, date.fromisoformat(db.today())
        ),
    }


# --- Checkpoint -------------------------------------------------------------


def run_checkpoint(
    conn: sqlite3.Connection,
    project: db.Project,
    progress: str,
    stage: db.Stage | None = None,
) -> dict:
    """Avalia o relato contra o objetivo do projeto e salva o checkpoint.

    Com etapas cadastradas, o modelo recebe prazos e critérios de pronto — é o que
    permite julgar contra régua verificável em vez da impressão do relato.

    Retorna a avaliação em blocos (para a web) e em markdown (para a CLI).
    """
    deadline = f"Prazo da entrega: {project.deadline}\n" if project.deadline else ""
    focus = f"Etapa em foco: {stage.name}\n" if stage else ""
    stages = context.stages_block(conn, project.id, stage_id=stage.id if stage else None)
    user_message = (
        f"Hoje é {db.today()}.\n"
        f"Projeto: {project.name}\n"
        f"Objetivo da entrega: {project.goal}\n"
        f"{deadline}{focus}\n"
        f"Etapas do projeto:\n{stages}\n\n"
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
    checkpoint = db.add_checkpoint(
        conn,
        project.id,
        progress,
        markdown,
        status=result["status"],
        summary=result["resumo"],
        stage_id=stage.id if stage else None,
    )
    verdicts = _save_verdicts(conn, project, checkpoint, result.get("vereditos") or [])
    return {
        "blocks": [
            {"title": "Situação", "body": result["situacao"]},
            {"title": "Riscos e desvios", "body": result["riscos"]},
            {"title": "Próximo passo", "body": steps},
        ],
        "markdown": markdown,
        "status": result["status"],
        "summary": result["resumo"],
        "verdicts": verdicts,
    }


def _save_verdicts(
    conn: sqlite3.Connection,
    project: db.Project,
    checkpoint: db.Checkpoint,
    raw: list[dict],
) -> list[dict]:
    """Casa os vereditos do modelo (que vêm por nome) com as etapas reais.

    Nome que não casa é descartado — alucinação não vira linha no banco. Etapa que
    o modelo omitiu entra como `nao_avaliada`, para o histórico ficar completo.
    """
    stages = db.list_stages(conn, project.id)
    if not stages:
        return []
    by_name = {s.name.strip().lower(): s for s in stages}
    matched: dict[int, dict] = {}
    for item in raw:
        stage = by_name.get(str(item.get("etapa", "")).strip().lower())
        if stage is None:
            continue
        matched[stage.id] = {
            "stage_id": stage.id,
            "verdict": item.get("veredito", "nao_avaliada"),
            "rationale": item.get("justificativa"),
        }
    rows = [
        matched.get(s.id, {"stage_id": s.id, "verdict": "nao_avaliada", "rationale": None})
        for s in stages
    ]
    db.add_checkpoint_verdicts(conn, checkpoint.id, rows)
    names = {s.id: s.name for s in stages}
    return [
        {
            "stage_id": r["stage_id"],
            "stage_name": names[r["stage_id"]],
            "verdict": r["verdict"],
            "label": db.VERDICT_LABELS[r["verdict"]],
            "rationale": r["rationale"],
        }
        for r in rows
    ]


# --- Review -----------------------------------------------------------------


def _rate(part: int, whole: int) -> float | None:
    """Proporção 0..1 arredondada; None quando não há base de cálculo."""
    return round(part / whole, 2) if whole else None


def _avg_lead_days(tasks: list[db.Task]) -> float | None:
    """Lead time médio (criação → conclusão) em dias, para tarefas concluídas."""
    leads = [
        (datetime.fromisoformat(t.done_at) - datetime.fromisoformat(t.created_at)).total_seconds()
        / 86400
        for t in tasks
        if t.done_at and t.created_at
    ]
    return round(sum(leads) / len(leads), 1) if leads else None


def review_metrics(conn: sqlite3.Connection, days: int = 14) -> dict:
    """Métricas de execução do período — só dados locais, sem LLM."""
    end = date.today()
    start = end - timedelta(days=days - 1)
    today = end.isoformat()
    tasks = db.list_tasks_between(conn, start.isoformat(), today)

    done = [t for t in tasks if t.status == "done"]
    pending = [t for t in tasks if t.status != "done"]
    overdue = [t for t in pending if t.due_date and t.due_date < today]
    done_with_due = [t for t in done if t.due_date]
    on_time = [t for t in done_with_due if (t.done_at or "")[:10] <= t.due_date]
    same_day = [t for t in done if (t.done_at or "")[:10] == t.day]
    unplanned = [t for t in tasks if t.source != "plan"]

    done_per_day = {
        (start + timedelta(days=i)).isoformat(): 0 for i in range(days)
    }
    for t in done:
        d = (t.done_at or "")[:10]
        if d in done_per_day:
            done_per_day[d] += 1

    by_effort = {}
    for level in db.EFFORT_LEVELS:
        subset = [t for t in tasks if t.effort == level]
        if subset:
            by_effort[level] = {
                "total": len(subset),
                "done": sum(1 for t in subset if t.status == "done"),
                "avg_lead_days": _avg_lead_days([t for t in subset if t.status == "done"]),
            }

    grouped: dict[str, list[db.Task]] = {}
    for t in tasks:
        for tag in (t.tags or "").split(","):
            if tag:
                grouped.setdefault(tag, []).append(t)
    by_tag = {
        tag: {
            "total": len(ts),
            "done": sum(1 for t in ts if t.status == "done"),
            "overdue": sum(
                1 for t in ts if t.status != "done" and t.due_date and t.due_date < today
            ),
            "avg_lead_days": _avg_lead_days([t for t in ts if t.status == "done"]),
        }
        for tag, ts in sorted(grouped.items())
    }

    grouped_by_project: dict[int, list[db.Task]] = {}
    for t in tasks:
        if t.project_id:
            grouped_by_project.setdefault(t.project_id, []).append(t)
    # kind=None: ciclos de rotina também precisam de nome nas métricas.
    project_names = {
        p.id: p.name for p in db.list_projects(conn, include_done=True, kind=None)
    }
    by_project = {
        str(pid): {
            "name": project_names.get(pid, f"Projeto #{pid}"),
            "total": len(ts),
            "done": sum(1 for t in ts if t.status == "done"),
            "overdue": sum(
                1 for t in ts if t.status != "done" and t.due_date and t.due_date < today
            ),
            "avg_lead_days": _avg_lead_days([t for t in ts if t.status == "done"]),
        }
        for pid, ts in sorted(grouped_by_project.items())
    }

    return {
        "period": {"start": start.isoformat(), "end": today, "days": days},
        "total": len(tasks),
        "done": len(done),
        "pending": len(pending),
        "overdue": [{"id": t.id, "title": t.title, "due": t.due_date} for t in overdue],
        "on_time_rate": _rate(len(on_time), len(done_with_due)),
        "carryover_rate": _rate(len(done) - len(same_day), len(done)),
        "unplanned_rate": _rate(len(unplanned), len(tasks)),
        "avg_lead_days": _avg_lead_days(done),
        "throughput_per_week": round(len(done) * 7 / days, 1),
        "done_per_day": [{"day": d, "done": n} for d, n in done_per_day.items()],
        "by_effort": by_effort,
        "by_tag": by_tag,
        "by_project": by_project,
    }


def _pct(rate: float | None) -> str:
    return f"{rate:.0%}" if rate is not None else "sem dados"


def _metrics_context(m: dict) -> str:
    """Formata as métricas em PT-BR para servir de contexto ao modelo."""
    lines = [
        f"Período: {m['period']['start']} a {m['period']['end']} ({m['period']['days']} dias).",
        f"Tarefas: {m['total']} no total, {m['done']} concluídas, {m['pending']} pendentes"
        f" ({len(m['overdue'])} atrasadas).",
        f"Entrega no prazo: {_pct(m['on_time_rate'])} das concluídas que tinham prazo.",
        f"Viraram o dia (carryover): {_pct(m['carryover_rate'])} das concluídas.",
        f"Trabalho não planejado (fora do plano do dia): {_pct(m['unplanned_rate'])}.",
        f"Lead time médio: {m['avg_lead_days'] if m['avg_lead_days'] is not None else 'sem dados'}"
        f" dias. Throughput: {m['throughput_per_week']} tarefas/semana.",
    ]
    if m["overdue"]:
        lines.append("Tarefas atrasadas:")
        lines.extend(f"- {t['title']} (prazo {t['due']})" for t in m["overdue"])
    if m["by_effort"]:
        lines.append("Por esforço estimado:")
        lines.extend(
            f"- {level}: {s['total']} tarefas, {s['done']} concluídas,"
            f" lead médio {s['avg_lead_days'] if s['avg_lead_days'] is not None else 'sem dados'} dias"
            for level, s in m["by_effort"].items()
        )
    if m["by_tag"]:
        lines.append("Por tag:")
        lines.extend(
            f"- {tag}: {s['total']} tarefas, {s['done']} concluídas, {s['overdue']} atrasadas,"
            f" lead médio {s['avg_lead_days'] if s['avg_lead_days'] is not None else 'sem dados'} dias"
            for tag, s in m["by_tag"].items()
        )
    if m["by_project"]:
        lines.append("Por projeto:")
        lines.extend(
            f"- {s['name']}: {s['total']} tarefas, {s['done']} concluídas, {s['overdue']} atrasadas,"
            f" lead médio {s['avg_lead_days'] if s['avg_lead_days'] is not None else 'sem dados'} dias"
            for s in m["by_project"].values()
        )
    return "\n".join(lines)


def run_review(conn: sqlite3.Connection, days: int = 14) -> dict:
    """Calcula as métricas do período e pede ao modelo uma avaliação de execução."""
    metrics = review_metrics(conn, days)
    if metrics["total"] == 0:
        raise LookupError("Sem tarefas no período — nada para analisar.")
    assessment = llm.complete(
        llm.load_prompt("review"), _metrics_context(metrics), quality=True
    )
    return {"metrics": metrics, "assessment": assessment}


# --- Chat -------------------------------------------------------------------


def chat_system(conn: sqlite3.Connection) -> str:
    return (
        llm.load_prompt("chat")
        + f"\n\nTarefas de hoje:\n{context.tasks_block(conn)}"
        + f"\n\nProjetos ativos:\n{context.projects_block(conn)}"
        + f"\n\nRotinas em andamento:\n{context.routine_runs_block(conn)}"
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
