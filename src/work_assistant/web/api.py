"""API da interface web (`wa web`).

Camada fina sobre `services.py` e `db.py` — nada de lógica de negócio aqui.
Servida junto com o frontend estático (`static/index.html`) pelo uvicorn.
"""

from pathlib import Path

import openai
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from work_assistant import config, db, services

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


class StandupIn(BaseModel):
    days: int = 1


class ReviewIn(BaseModel):
    days: int = 14


class ChatIn(BaseModel):
    message: str
    history: list[dict] = []


class TaskProjectIn(BaseModel):
    project_id: int | None = None


class TaskEditIn(BaseModel):
    project_id: int | None = None
    tags: list[str] = []
    due_date: str | None = None
    effort: str | None = None


def _project_map(conn) -> dict[int, str]:
    return {p.id: p.name for p in db.list_projects(conn, include_done=True)}


def _task_out(t: db.Task, project_map: dict[int, str] | None = None) -> dict:
    project_map = project_map or {}
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
    }


def _project_out(conn, p: db.Project) -> dict:
    checkpoints = db.list_checkpoints(conn, p.id)
    if p.status == "done":
        tag = "concluído"
    elif not checkpoints:
        tag = "sem checkpoint"
    else:
        tag = checkpoints[-1].status or "sem checkpoint"
    project_tasks = db.list_tasks_by_project(conn, p.id)
    return {
        "id": p.id,
        "name": p.name,
        "goal": p.goal,
        "deadline": p.deadline,
        "active": p.status == "active",
        "tag": tag,
        "tasks": {
            "total": len(project_tasks),
            "done": sum(1 for t in project_tasks if t.status == "done"),
        },
        "timeline": [
            {
                "date": c.created_at[:10],
                "status": c.status,
                "summary": c.summary or c.assessment.split("\n")[0][:100],
            }
            for c in checkpoints
        ],
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
    today = db.today()
    project_map = _project_map(conn)
    return {
        "today": today,
        "day": day or today,
        "user_name": config.USER_NAME,
        "model": config.LLM_MODEL,
        "tasks": [_task_out(t, project_map) for t in db.list_tasks(conn, day=day)],
        "projects": [_project_out(conn, p) for p in db.list_projects(conn, include_done=True)],
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
    return _task_out(task, _project_map(conn))


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
    return _task_out(task, _project_map(conn))


@app.post("/api/tasks/{task_id}/project")
def set_task_project(task_id: int, body: TaskProjectIn):
    conn = db.connect()
    try:
        task = db.set_task_project(conn, task_id, body.project_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _task_out(task, _project_map(conn))


@app.post("/api/tasks/{task_id}")
def edit_task(task_id: int, body: TaskEditIn):
    """Atualiza projeto, tags, prazo e esforço de uma tarefa (popover de edição da web)."""
    conn = db.connect()
    try:
        db.get_task(conn, task_id)
        db.set_task_project(conn, task_id, body.project_id)
        db.set_task_tags(conn, task_id, body.tags)
        db.set_task_due(conn, task_id, body.due_date or None)
        task = db.set_task_effort(conn, task_id, body.effort or None)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _task_out(task, _project_map(conn))


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
    return _project_out(conn, project)


@app.post("/api/projects/{project_id}/done")
def finish_project(project_id: int):
    conn = db.connect()
    try:
        project = db.complete_project(conn, project_id)
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


@app.post("/api/standup")
def standup(body: StandupIn):
    conn = db.connect()
    try:
        return _llm_call(services.run_standup, conn, body.days)
    except LookupError as e:
        raise HTTPException(status_code=409, detail=str(e))


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
