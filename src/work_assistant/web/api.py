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


class ProjectIn(BaseModel):
    name: str
    goal: str


class PlanIn(BaseModel):
    relato: str


class PlanSaveIn(BaseModel):
    tasks: list[dict]


class CheckpointIn(BaseModel):
    project_id: int
    progress: str


class StandupIn(BaseModel):
    days: int = 1


class ChatIn(BaseModel):
    message: str
    history: list[dict] = []


def _task_out(t: db.Task) -> dict:
    return {
        "id": t.id,
        "title": t.title,
        "priority": t.priority,
        "done": t.status == "done",
        "day": t.day,
    }


def _project_out(conn, p: db.Project) -> dict:
    checkpoints = db.list_checkpoints(conn, p.id)
    if p.status == "done":
        tag = "concluído"
    elif not checkpoints:
        tag = "sem checkpoint"
    else:
        tag = checkpoints[-1].status or "sem checkpoint"
    return {
        "id": p.id,
        "name": p.name,
        "goal": p.goal,
        "active": p.status == "active",
        "tag": tag,
        "timeline": [
            {
                "date": c.created_at[:10],
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
    return {
        "today": today,
        "day": day or today,
        "user_name": config.USER_NAME,
        "model": config.LLM_MODEL,
        "tasks": [_task_out(t) for t in db.list_tasks(conn, day=day)],
        "projects": [_project_out(conn, p) for p in db.list_projects(conn, include_done=True)],
    }


@app.post("/api/tasks")
def add_task(body: TaskIn):
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Título vazio.")
    conn = db.connect()
    return _task_out(db.add_task(conn, title))


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
    return _task_out(task)


@app.post("/api/projects")
def add_project(body: ProjectIn):
    name, goal = body.name.strip(), body.goal.strip()
    if not name or not goal:
        raise HTTPException(status_code=422, detail="Preencha nome e objetivo do projeto.")
    conn = db.connect()
    return _project_out(conn, db.add_project(conn, name, goal))


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
    return {"tasks": [_task_out(t) for t in db.list_tasks(conn)]}


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


@app.post("/api/chat")
def chat(body: ChatIn):
    conn = db.connect()
    return {"reply": _llm_call(services.chat_reply, conn, body.message, body.history)}
