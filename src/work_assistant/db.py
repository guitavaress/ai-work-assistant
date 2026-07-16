"""Persistência em SQLite: tarefas, projetos e checkpoints."""

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from work_assistant import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    goal TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',  -- active | done
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    project_id INTEGER REFERENCES projects(id),
    day TEXT NOT NULL,                       -- data (YYYY-MM-DD) do to-do a que pertence
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | done
    priority INTEGER,                        -- 1 = mais alta; NULL = sem prioridade
    created_at TEXT NOT NULL,
    done_at TEXT
);

CREATE TABLE IF NOT EXISTS checkpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    progress TEXT NOT NULL,    -- o que o usuário relatou
    assessment TEXT NOT NULL,  -- avaliação gerada pelo modelo
    created_at TEXT NOT NULL
);
"""


@dataclass
class Task:
    id: int
    title: str
    project_id: int | None
    day: str
    status: str
    priority: int | None
    created_at: str
    done_at: str | None


@dataclass
class Project:
    id: int
    name: str
    goal: str
    status: str
    created_at: str


@dataclass
class Checkpoint:
    id: int
    project_id: int
    progress: str
    assessment: str
    created_at: str


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def today() -> str:
    return date.today().isoformat()


# --- Tarefas ---------------------------------------------------------------


def add_task(
    conn: sqlite3.Connection,
    title: str,
    project_id: int | None = None,
    day: str | None = None,
    priority: int | None = None,
) -> Task:
    cur = conn.execute(
        "INSERT INTO tasks (title, project_id, day, priority, created_at) VALUES (?, ?, ?, ?, ?)",
        (title, project_id, day or today(), priority, _now()),
    )
    conn.commit()
    return get_task(conn, cur.lastrowid)


def get_task(conn: sqlite3.Connection, task_id: int) -> Task:
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if row is None:
        raise LookupError(f"Tarefa #{task_id} não encontrada")
    return Task(**row)


def list_tasks(
    conn: sqlite3.Connection,
    day: str | None = None,
    include_done: bool = True,
) -> list[Task]:
    query = "SELECT * FROM tasks WHERE day = ?"
    params: list = [day or today()]
    if not include_done:
        query += " AND status = 'pending'"
    query += " ORDER BY priority IS NULL, priority, id"
    return [Task(**row) for row in conn.execute(query, params)]


def list_tasks_between(conn: sqlite3.Connection, start: str, end: str) -> list[Task]:
    rows = conn.execute(
        "SELECT * FROM tasks WHERE day BETWEEN ? AND ? ORDER BY day, id", (start, end)
    )
    return [Task(**row) for row in rows]


def complete_task(conn: sqlite3.Connection, task_id: int) -> Task:
    get_task(conn, task_id)
    conn.execute(
        "UPDATE tasks SET status = 'done', done_at = ? WHERE id = ?", (_now(), task_id)
    )
    conn.commit()
    return get_task(conn, task_id)


def set_task_priority(conn: sqlite3.Connection, task_id: int, priority: int) -> Task:
    get_task(conn, task_id)
    conn.execute("UPDATE tasks SET priority = ? WHERE id = ?", (priority, task_id))
    conn.commit()
    return get_task(conn, task_id)


# --- Projetos ---------------------------------------------------------------


def add_project(conn: sqlite3.Connection, name: str, goal: str) -> Project:
    cur = conn.execute(
        "INSERT INTO projects (name, goal, created_at) VALUES (?, ?, ?)",
        (name, goal, _now()),
    )
    conn.commit()
    return get_project(conn, cur.lastrowid)


def get_project(conn: sqlite3.Connection, project_id: int) -> Project:
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        raise LookupError(f"Projeto #{project_id} não encontrado")
    return Project(**row)


def find_project(conn: sqlite3.Connection, ref: str) -> Project:
    """Busca projeto por id numérico ou por nome (case-insensitive)."""
    if ref.isdigit():
        return get_project(conn, int(ref))
    row = conn.execute(
        "SELECT * FROM projects WHERE lower(name) = lower(?)", (ref,)
    ).fetchone()
    if row is None:
        raise LookupError(f"Projeto '{ref}' não encontrado")
    return Project(**row)


def list_projects(conn: sqlite3.Connection, include_done: bool = False) -> list[Project]:
    query = "SELECT * FROM projects"
    if not include_done:
        query += " WHERE status = 'active'"
    query += " ORDER BY id"
    return [Project(**row) for row in conn.execute(query)]


def complete_project(conn: sqlite3.Connection, project_id: int) -> Project:
    get_project(conn, project_id)
    conn.execute("UPDATE projects SET status = 'done' WHERE id = ?", (project_id,))
    conn.commit()
    return get_project(conn, project_id)


# --- Checkpoints ------------------------------------------------------------


def add_checkpoint(
    conn: sqlite3.Connection, project_id: int, progress: str, assessment: str
) -> Checkpoint:
    get_project(conn, project_id)
    cur = conn.execute(
        "INSERT INTO checkpoints (project_id, progress, assessment, created_at) VALUES (?, ?, ?, ?)",
        (project_id, progress, assessment, _now()),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM checkpoints WHERE id = ?", (cur.lastrowid,)).fetchone()
    return Checkpoint(**row)


def list_checkpoints(conn: sqlite3.Connection, project_id: int) -> list[Checkpoint]:
    rows = conn.execute(
        "SELECT * FROM checkpoints WHERE project_id = ? ORDER BY id", (project_id,)
    )
    return [Checkpoint(**row) for row in rows]
