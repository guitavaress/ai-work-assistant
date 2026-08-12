"""API da interface web (`wa web`).

Camada fina sobre `services.py` e `db.py` — nada de lógica de negócio aqui.
Servida junto com o frontend estático (`static/index.html`) pelo uvicorn.
"""

import sqlite3
from datetime import date
from pathlib import Path

import openai
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from work_assistant import config, db, schedule, services

STATIC_DIR = Path(__file__).parent / "static"

OFFLINE_MSG = "Servidor offline — suba o llama.cpp com docker compose up -d"

app = FastAPI(title="AI Work Assistant", docs_url=None, redoc_url=None)


class TaskIn(BaseModel):
    title: str
    due_date: str | None = None
    tags: list[str] = []
    effort: str | None = None
    project_id: int | None = None


class ProjectIn(BaseModel):
    name: str
    goal: str
    deadline: str | None = None


class PlanIn(BaseModel):
    relato: str


class PlanSaveIn(BaseModel):
    tasks: list[dict]


class CheckpointIn(BaseModel):
    project_id: int
    progress: str


class ReviewIn(BaseModel):
    days: int = 14


class ChatIn(BaseModel):
    message: str
    history: list[dict] = []


class RoutineStepIn(BaseModel):
    name: str
    done_criteria: str
    offset_days: int = 0


class RoutineIn(BaseModel):
    name: str
    goal: str
    cadence: str = "monthly"
    anchor: int = 1
    sla_days: int = 1
    steps: list[RoutineStepIn] = []


class RoutineRunIn(BaseModel):
    period: str | None = None


class TaskProjectIn(BaseModel):
    project_id: int | None = None


class TaskEditIn(BaseModel):
    project_id: int | None = None
    stage_id: int | None = None
    tags: list[str] = []
    due_date: str | None = None
    effort: str | None = None


def _project_map(conn) -> dict[int, str]:
    # kind=None: a tarefa de um ciclo de rotina também precisa exibir o nome do ciclo.
    return {p.id: p.name for p in db.list_projects(conn, include_done=True, kind=None)}


def _kind_map(conn) -> dict[int, str]:
    return {p.id: p.kind for p in db.list_projects(conn, include_done=True, kind=None)}


def _days_between(start: str, end: str) -> int:
    """Dias de `start` até `end` (negativo se `end` for anterior)."""
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def _task_out(
    t: db.Task,
    project_map: dict[int, str] | None = None,
    stage_map: dict[int, str] | None = None,
    kind_map: dict[int, str] | None = None,
) -> dict:
    project_map = project_map or {}
    stage_map = stage_map or {}
    kind_map = kind_map or {}
    return {
        "id": t.id,
        "title": t.title,
        "priority": t.priority,
        "done": t.status == "done",
        "day": t.day,
        "due": t.due_date,
        "tags": t.tags.split(",") if t.tags else [],
        "effort": t.effort,
        "source": t.source,
        "project_id": t.project_id,
        "project_name": project_map.get(t.project_id),
        "project_kind": kind_map.get(t.project_id),
        "stage_id": t.stage_id,
        "stage_name": stage_map.get(t.stage_id),
    }


def _stage_out(s: db.Stage, today: str, progress: dict, verdict: db.CheckpointVerdict | None,
               is_current: bool) -> dict:
    done = s.status == "done"
    overdue = bool(not done and s.deadline and s.deadline < today)
    return {
        "id": s.id,
        "name": s.name,
        "position": s.position,
        "deadline": s.deadline,
        "done": done,
        "done_at": s.done_at,
        "overdue": overdue,
        "days_overdue": _days_between(s.deadline, today) if overdue else 0,
        "is_current": is_current,
        "done_criteria": s.done_criteria,
        "tasks": progress,
        "verdict": (
            {
                "verdict": verdict.verdict,
                "label": db.VERDICT_LABELS[verdict.verdict],
                "rationale": verdict.rationale,
                "date": verdict.created_at[:10],
            }
            if verdict
            else None
        ),
    }


def _project_out(conn, p: db.Project, today: str | None = None) -> dict:
    """Serializa projeto ou ciclo com etapas, progresso e vereditos.

    O que é derivado de data (atrasado, dias de atraso, etapa corrente) é calculado
    AQUI e não no navegador: o relógio do browser divergiria do `db.today()` que a
    CLI usa, e a linha vermelha da web discordaria do `wa todo list`.
    """
    today = today or db.today()
    checkpoints = db.list_checkpoints(conn, p.id)
    if p.status == "done":
        tag = "concluído"
    elif not checkpoints:
        tag = "sem checkpoint"
    else:
        tag = checkpoints[-1].status or "sem checkpoint"

    stages = db.list_stages(conn, p.id)
    progress = db.stage_progress_map(conn, p.id)
    verdicts = db.last_stage_verdicts(conn, p.id)
    current = next((s for s in stages if s.status != "done"), None)
    stages_out = [
        _stage_out(
            s,
            today,
            progress.get(s.id, {"total": 0, "done": 0}),
            verdicts.get(s.id),
            is_current=bool(current and s.id == current.id),
        )
        for s in stages
    ]
    overdue_now = p.status == "active" and p.deadline and p.deadline < today
    return {
        "id": p.id,
        "name": p.name,
        "goal": p.goal,
        "deadline": p.deadline,
        "active": p.status == "active",
        "kind": p.kind,
        "done_at": p.done_at,
        "days_overdue": _days_between(p.deadline, today) if overdue_now else 0,
        "tag": tag,
        "tasks": db.project_progress(conn, p.id),
        "stages": stages_out,
        "stages_progress": {
            "total": len(stages_out),
            "done": sum(1 for s in stages_out if s["done"]),
            "overdue": sum(1 for s in stages_out if s["overdue"]),
        },
        "current_stage_id": current.id if current else None,
        "timeline": [
            {
                "date": c.created_at[:10],
                "status": c.status,
                "summary": c.summary or c.assessment.split("\n")[0][:100],
            }
            for c in checkpoints
        ],
    }


def _run_out(conn, p: db.Project, routines: dict[int, db.Routine], today: str) -> dict:
    """Ciclo de rotina: o projeto serializado mais o vocabulário da rotina-mãe."""
    out = _project_out(conn, p, today)
    routine = routines.get(p.routine_id)
    open_ = p.status == "active"
    out.update(
        {
            "routine_id": p.routine_id,
            "routine_name": routine.name if routine else None,
            "period": p.period,
            "period_label": (
                schedule.period_label(routine.cadence, p.period) if routine and p.period else None
            ),
            "cadence": schedule.cadence_label(routine.cadence) if routine else None,
            "window_label": (
                schedule.window_label(routine.cadence, routine.anchor, routine.sla_days)
                if routine
                else None
            ),
            "sla_days": routine.sla_days if routine else None,
            "sla_left_days": _days_between(today, p.deadline) if p.deadline else None,
            "open": open_,
            # None = fechado sem data registrada (ciclo anterior à migração do done_at).
            "closed_on_time": (
                None
                if open_ or not p.done_at or not p.deadline
                else p.done_at[:10] <= p.deadline
            ),
        }
    )
    return out


def _routine_out(conn, r: db.Routine, today: str) -> dict:
    """Molde da rotina — a aba Rotinas mostra os ciclos, isto é o cabeçalho deles."""
    runs = db.list_routine_runs(conn, r.id)
    closed = [p for p in runs if p.status == "done" and p.done_at and p.deadline]
    on_time = sum(1 for p in closed if p.done_at[:10] <= p.deadline)
    # O ciclo do período corrente decide o que o card do molde oferece. Sem isto o
    # front só sabe se existe ciclo ABERTO, e um ciclo fechado no mesmo período
    # vira botão "abrir ciclo agora" que não abre nada — `materialize_run` é
    # idempotente por período e devolve o fechado.
    current_period = schedule.period_key(r.cadence, date.fromisoformat(today))
    current = next((p for p in runs if p.period == current_period), None)
    return {
        "id": r.id,
        "name": r.name,
        "goal": r.goal,
        "cadence": schedule.cadence_label(r.cadence),
        "window_label": schedule.window_label(r.cadence, r.anchor, r.sla_days),
        "sla_days": r.sla_days,
        "active": r.status == "active",
        "next_open": schedule.next_open(
            r.cadence, r.anchor, date.fromisoformat(today)
        ).isoformat(),
        "current_period": current_period,
        "current_period_label": schedule.period_label(r.cadence, current_period),
        "current_run": (
            {"id": current.id, "open": current.status == "active"} if current else None
        ),
        "steps": [
            {
                "position": s.position,
                "name": s.name,
                "offset_days": s.offset_days,
                "done_criteria": s.done_criteria,
            }
            for s in db.list_routine_steps(conn, r.id)
        ],
        # Denominador só com ciclos que têm data de fechamento: os anteriores à
        # migração do done_at ficam fora, em vez de contar como cumpridos.
        "sla_history": {
            "closed": len(closed),
            "on_time": on_time,
            "rate": round(on_time / len(closed), 2) if closed else None,
        },
    }


def _llm_call(fn, *args, **kwargs):
    """Executa uma chamada ao modelo traduzindo falha de conexão em 503."""
    try:
        return fn(*args, **kwargs)
    except openai.APIConnectionError:
        raise HTTPException(status_code=503, detail=OFFLINE_MSG)


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health():
    return {"online": services.llm_online(), "model": config.LLM_MODEL}


@app.get("/api/state")
def state(day: str | None = None):
    conn = db.connect()
    services.ensure_routines(conn)
    today = db.today()
    project_map = _project_map(conn)
    stage_map = db.stage_names(conn)
    kind_map = _kind_map(conn)
    routines = {r.id: r for r in db.list_routines(conn, include_archived=True)}
    runs = db.list_projects(conn, include_done=True, kind="routine_run")
    return {
        "today": today,
        "day": day or today,
        "user_name": config.USER_NAME,
        "model": config.LLM_MODEL,
        "tasks": [
            _task_out(t, project_map, stage_map, kind_map)
            for t in db.list_tasks(conn, day=day)
        ],
        "projects": [
            _project_out(conn, p, today) for p in db.list_projects(conn, include_done=True)
        ],
        # Ciclos de rotina vêm numa chave própria: fora de `projects` para não poluir a
        # aba Projetos, mas disponíveis para o popover de edição — sem eles o <select>
        # não teria a opção da tarefa e o save apagaria o vínculo em silêncio.
        "routine_runs": [_run_out(conn, p, routines, today) for p in runs],
        "routines": [
            _routine_out(conn, r, today) for r in db.list_routines(conn)
        ],
        "ritual": services.day_ritual(conn, today),
        "counts": {"rotinas": sum(1 for p in runs if p.status == "active")},
    }


@app.post("/api/tasks")
def add_task(body: TaskIn):
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Título vazio.")
    conn = db.connect()
    try:
        task = db.add_task(
            conn,
            title,
            project_id=body.project_id,
            due_date=body.due_date or None,
            tags=body.tags,
            effort=body.effort,
        )
    except (ValueError, LookupError) as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _task_out(task, _project_map(conn), db.stage_names(conn), _kind_map(conn))


@app.post("/api/tasks/{task_id}/toggle")
def toggle_task(task_id: int):
    conn = db.connect()
    try:
        task = db.get_task(conn, task_id)
        if task.status == "done":
            task = db.reopen_task(conn, task_id)
        else:
            task = db.complete_task(conn, task_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _task_out(task, _project_map(conn), db.stage_names(conn), _kind_map(conn))


@app.post("/api/tasks/{task_id}/project")
def set_task_project(task_id: int, body: TaskProjectIn):
    conn = db.connect()
    try:
        task = db.set_task_project(conn, task_id, body.project_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _task_out(task, _project_map(conn), db.stage_names(conn), _kind_map(conn))


@app.post("/api/tasks/{task_id}")
def edit_task(task_id: int, body: TaskEditIn):
    """Atualiza projeto, etapa, tags, prazo e esforço (popover de edição da web)."""
    conn = db.connect()
    try:
        db.get_task(conn, task_id)
        if body.stage_id is not None and body.project_id is not None:
            # Sem esta guarda `set_task_stage` moveria a tarefa para o projeto da
            # etapa em silêncio, contrariando o destino que o usuário escolheu.
            if db.get_stage(conn, body.stage_id).project_id != body.project_id:
                raise HTTPException(
                    status_code=422, detail="Etapa não pertence ao projeto escolhido."
                )
        # Ordem importa: o projeto primeiro (solta a etapa se mudou de destino),
        # a etapa depois (ela manda e reafirma o project_id).
        db.set_task_project(conn, task_id, body.project_id)
        db.set_task_stage(conn, task_id, body.stage_id)
        db.set_task_tags(conn, task_id, body.tags)
        db.set_task_due(conn, task_id, body.due_date or None)
        task = db.set_task_effort(conn, task_id, body.effort or None)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _task_out(task, _project_map(conn), db.stage_names(conn), _kind_map(conn))


@app.post("/api/projects")
def add_project(body: ProjectIn):
    name, goal = body.name.strip(), body.goal.strip()
    if not name or not goal:
        raise HTTPException(status_code=422, detail="Preencha nome e objetivo do projeto.")
    conn = db.connect()
    try:
        project = db.add_project(conn, name, goal, deadline=body.deadline or None)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=422, detail="Já existe um projeto com esse nome.")
    return _project_out(conn, project)


@app.post("/api/routines")
def add_routine(body: RoutineIn):
    """Cria a rotina com o checklist inteiro, num POST só (formulário da web)."""
    name, goal = body.name.strip(), body.goal.strip()
    if not name or not goal:
        raise HTTPException(
            status_code=422, detail="Preencha nome e o que é fechar o ciclo."
        )
    if not body.steps:
        raise HTTPException(
            status_code=422, detail="Adicione ao menos uma etapa com critério de pronto."
        )
    steps = []
    for step in body.steps:
        step_name = step.name.strip()
        criteria = (step.done_criteria or "").strip()
        if not step_name or not criteria:
            raise HTTPException(
                status_code=422, detail="Etapa precisa de nome e critério de pronto."
            )
        steps.append(
            {"name": step_name, "done_criteria": criteria, "offset_days": step.offset_days}
        )

    conn = db.connect()
    try:
        routine = db.add_routine(
            conn, name, goal, body.cadence, body.anchor, sla_days=body.sla_days
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=422, detail="Já existe uma rotina com esse nome.")
    db.replace_routine_steps(conn, routine.id, steps)
    # Não materializa aqui de propósito: o ciclo nasce quando a janela abrir, e
    # o botão "abrir ciclo agora" da aba Rotinas é a válvula para o resto.
    return _routine_out(conn, routine, db.today())


@app.get("/api/routines/preview")
def routine_preview(cadence: str = "monthly", anchor: int = 1, sla_days: int = 1):
    """Rótulo da janela para o formulário, sem precisar salvar a rotina.

    É endpoint e não função JS porque `schedule.window_label` é a fonte única
    dessa frase — a CLI e o /api/state usam a mesma. Duplicar em JS criaria
    duas verdades para o mesmo texto.
    """
    try:
        return {
            "cadence": schedule.cadence_label(cadence),
            "window_label": schedule.window_label(cadence, anchor, sla_days),
            "next_open": schedule.next_open(
                cadence, anchor, date.fromisoformat(db.today())
            ).isoformat(),
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@app.post("/api/routines/{routine_id}/run")
def run_routine(routine_id: int, body: RoutineRunIn | None = None):
    """Materializa o ciclo de um período — idempotente, devolve o existente."""
    conn = db.connect()
    try:
        routine = db.get_routine(conn, routine_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    period = (body.period if body else None) or schedule.period_key(
        routine.cadence, date.fromisoformat(db.today())
    )
    try:
        run = services.materialize_run(conn, routine, period)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    routines = {r.id: r for r in db.list_routines(conn, include_archived=True)}
    return _run_out(conn, run, routines, db.today())


@app.post("/api/stages/{stage_id}/toggle")
def toggle_stage(stage_id: int):
    """Fecha ou reabre uma etapa — é o checkbox do checklist na web.

    Toggle e não `done` porque a etapa marcada por engano precisa de volta: a CLI
    só tem `wa project stage done`, e sem isto reabrir exigiria SQL na mão.
    """
    conn = db.connect()
    try:
        stage = db.get_stage(conn, stage_id)
        if stage.status == "done":
            stage = db.reopen_stage(conn, stage_id)
        else:
            stage = db.complete_stage(conn, stage_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    stages = db.list_stages(conn, stage.project_id)
    current = next((s for s in stages if s.status != "done"), None)
    return _stage_out(
        stage,
        db.today(),
        db.stage_progress(conn, stage.id),
        db.last_stage_verdicts(conn, stage.project_id).get(stage.id),
        is_current=bool(current and current.id == stage.id),
    )


@app.post("/api/projects/{project_id}/done")
def finish_project(project_id: int):
    conn = db.connect()
    try:
        project = db.complete_project(conn, project_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _project_out(conn, project)


@app.post("/api/projects/{project_id}/reopen")
def reopen_project(project_id: int):
    """Reabre projeto ou ciclo fechado por engano.

    Sem isto o ciclo fechado antes da hora era beco sem saída: o período já tem
    ciclo (índice único), então `materialize_run` devolve o fechado em vez de
    criar outro, e não havia como voltar pela web.
    """
    conn = db.connect()
    try:
        project = db.reopen_project(conn, project_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _project_out(conn, project)


@app.post("/api/plan")
def plan(body: PlanIn):
    conn = db.connect()
    return {"tasks": _llm_call(services.suggest_plan, conn, body.relato)}


@app.post("/api/plan/save")
def plan_save(body: PlanSaveIn):
    conn = db.connect()
    services.save_plan(conn, body.tasks)
    return {"tasks": [_task_out(t, _project_map(conn)) for t in db.list_tasks(conn)]}


@app.post("/api/checkpoint")
def checkpoint(body: CheckpointIn):
    conn = db.connect()
    try:
        project = db.get_project(conn, body.project_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _llm_call(services.run_checkpoint, conn, project, body.progress)


@app.get("/api/review")
def review_metrics(days: int = 14):
    conn = db.connect()
    return services.review_metrics(conn, days)


@app.post("/api/review")
def review(body: ReviewIn):
    conn = db.connect()
    try:
        return _llm_call(services.run_review, conn, body.days)
    except LookupError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.post("/api/chat")
def chat(body: ChatIn):
    conn = db.connect()
    return {"reply": _llm_call(services.chat_reply, conn, body.message, body.history)}
