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
    deadline TEXT,                          -- data-alvo da entrega (YYYY-MM-DD)
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    project_id INTEGER REFERENCES projects(id),
    day TEXT NOT NULL,                       -- data (YYYY-MM-DD) do to-do a que pertence
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | done
    priority INTEGER,                        -- 1 = mais alta; NULL = sem prioridade
    due_date TEXT,                           -- prazo (YYYY-MM-DD); NULL = sem prazo
    tags TEXT,                               -- CSV lowercase (ex.: 'bug,reuniao')
    source TEXT NOT NULL DEFAULT 'manual',   -- manual | plan (origem da criação)
    effort TEXT,                             -- estimativa de esforço: P | M | G
    created_at TEXT NOT NULL,
    done_at TEXT
);

CREATE TABLE IF NOT EXISTS checkpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    progress TEXT NOT NULL,    -- o que o usuário relatou
    assessment TEXT NOT NULL,  -- avaliação gerada pelo modelo
    status TEXT,               -- no rumo | em risco | desviando (NULL em registros antigos)
    summary TEXT,              -- resumo de 1 frase para a timeline da interface web
    created_at TEXT NOT NULL
);
"""

# Colunas adicionadas depois do schema inicial: bancos existentes precisam de ALTER.
_MIGRATIONS = {
    "checkpoints": {
        "status": "ALTER TABLE checkpoints ADD COLUMN status TEXT",
        "summary": "ALTER TABLE checkpoints ADD COLUMN summary TEXT",
    },
    "tasks": {
        "due_date": "ALTER TABLE tasks ADD COLUMN due_date TEXT",
        "tags": "ALTER TABLE tasks ADD COLUMN tags TEXT",
        "source": "ALTER TABLE tasks ADD COLUMN source TEXT NOT NULL DEFAULT 'manual'",
        "effort": "ALTER TABLE tasks ADD COLUMN effort TEXT",
    },
    "projects": {
        "deadline": "ALTER TABLE projects ADD COLUMN deadline TEXT",
    },
}

EFFORT_LEVELS = ("P", "M", "G")

# Colunas explícitas (em vez de SELECT *) para não quebrar a construção das dataclasses
# quando o arquivo .db tem colunas extras vindas de outra branch (ex.: azdo-integration,
# que roda contra o mesmo ~/.ai-work-assistant/assistant.db e adiciona `external_ref`).
TASK_COLUMNS = (
    "id, title, project_id, day, status, priority, created_at, done_at,"
    " due_date, tags, source, effort"
)
PROJECT_COLUMNS = "id, name, goal, status, created_at, deadline"
CHECKPOINT_COLUMNS = "id, project_id, progress, assessment, status, summary, created_at"


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
    due_date: str | None = None
    tags: str | None = None
    source: str = "manual"
    effort: str | None = None


@dataclass
class Project:
    id: int
    name: str
    goal: str
    status: str
    created_at: str
    deadline: str | None = None


@dataclass
class Checkpoint:
    id: int
    project_id: int
    progress: str
    assessment: str
    status: str | None
    summary: str | None
    created_at: str


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    for table, columns in _MIGRATIONS.items():
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        for column, ddl in columns.items():
            if column not in existing:
                conn.execute(ddl)
    conn.commit()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def today() -> str:
    return date.today().isoformat()


def normalize_tags(tags: list[str] | str | None) -> str | None:
    """Aceita lista ou CSV; devolve CSV lowercase sem espaços/duplicatas (None se vazio)."""
    if tags is None:
        return None
    if isinstance(tags, str):
        tags = tags.split(",")
    cleaned = dict.fromkeys(t.strip().lower() for t in tags if t.strip())
    return ",".join(cleaned) or None


def validate_effort(effort: str | None) -> str | None:
    if effort is None:
        return None
    value = effort.strip().upper()
    if value not in EFFORT_LEVELS:
        raise ValueError(f"Esforço inválido '{effort}': use P, M ou G")
    return value


def validate_date(value: str | None, field: str = "data") -> str | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise ValueError(f"{field} inválida '{value}': use o formato YYYY-MM-DD") from None


# --- Tarefas ---------------------------------------------------------------


def add_task(
    conn: sqlite3.Connection,
    title: str,
    project_id: int | None = None,
    day: str | None = None,
    priority: int | None = None,
    due_date: str | None = None,
    tags: list[str] | str | None = None,
    source: str = "manual",
    effort: str | None = None,
) -> Task:
    if project_id is not None:
        get_project(conn, project_id)
    cur = conn.execute(
        "INSERT INTO tasks (title, project_id, day, priority, due_date, tags, source, effort,"
        " created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            title,
            project_id,
            day or today(),
            priority,
            validate_date(due_date, "prazo"),
            normalize_tags(tags),
            source,
            validate_effort(effort),
            _now(),
        ),
    )
    conn.commit()
    return get_task(conn, cur.lastrowid)


def get_task(conn: sqlite3.Connection, task_id: int) -> Task:
    row = conn.execute(f"SELECT {TASK_COLUMNS} FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if row is None:
        raise LookupError(f"Tarefa #{task_id} não encontrada")
    return Task(**row)


def list_tasks(
    conn: sqlite3.Connection,
    day: str | None = None,
    include_done: bool = True,
) -> list[Task]:
    query = f"SELECT {TASK_COLUMNS} FROM tasks WHERE day = ?"
    params: list = [day or today()]
    if not include_done:
        query += " AND status = 'pending'"
    query += " ORDER BY priority IS NULL, priority, id"
    return [Task(**row) for row in conn.execute(query, params)]


def list_tasks_between(conn: sqlite3.Connection, start: str, end: str) -> list[Task]:
    rows = conn.execute(
        f"SELECT {TASK_COLUMNS} FROM tasks WHERE day BETWEEN ? AND ? ORDER BY day, id", (start, end)
    )
    return [Task(**row) for row in rows]


def complete_task(conn: sqlite3.Connection, task_id: int) -> Task:
    get_task(conn, task_id)
    conn.execute(
        "UPDATE tasks SET status = 'done', done_at = ? WHERE id = ?", (_now(), task_id)
    )
    conn.commit()
    return get_task(conn, task_id)


def reopen_task(conn: sqlite3.Connection, task_id: int) -> Task:
    get_task(conn, task_id)
    conn.execute(
        "UPDATE tasks SET status = 'pending', done_at = NULL WHERE id = ?", (task_id,)
    )
    conn.commit()
    return get_task(conn, task_id)


def set_task_priority(conn: sqlite3.Connection, task_id: int, priority: int) -> Task:
    get_task(conn, task_id)
    conn.execute("UPDATE tasks SET priority = ? WHERE id = ?", (priority, task_id))
    conn.commit()
    return get_task(conn, task_id)


def set_task_due(conn: sqlite3.Connection, task_id: int, due_date: str | None) -> Task:
    get_task(conn, task_id)
    conn.execute(
        "UPDATE tasks SET due_date = ? WHERE id = ?",
        (validate_date(due_date, "prazo"), task_id),
    )
    conn.commit()
    return get_task(conn, task_id)


def set_task_tags(
    conn: sqlite3.Connection, task_id: int, tags: list[str] | str | None
) -> Task:
    get_task(conn, task_id)
    conn.execute(
        "UPDATE tasks SET tags = ? WHERE id = ?", (normalize_tags(tags), task_id)
    )
    conn.commit()
    return get_task(conn, task_id)


def set_task_effort(conn: sqlite3.Connection, task_id: int, effort: str | None) -> Task:
    get_task(conn, task_id)
    conn.execute(
        "UPDATE tasks SET effort = ? WHERE id = ?", (validate_effort(effort), task_id)
    )
    conn.commit()
    return get_task(conn, task_id)


def set_task_project(
    conn: sqlite3.Connection, task_id: int, project_id: int | None
) -> Task:
    get_task(conn, task_id)
    if project_id is not None:
        get_project(conn, project_id)
    conn.execute(
        "UPDATE tasks SET project_id = ? WHERE id = ?", (project_id, task_id)
    )
    conn.commit()
    return get_task(conn, task_id)


def list_tasks_by_project(
    conn: sqlite3.Connection, project_id: int, include_done: bool = True
) -> list[Task]:
    """Todas as tarefas do projeto, independente do dia do to-do."""
    query = f"SELECT {TASK_COLUMNS} FROM tasks WHERE project_id = ?"
    params: list = [project_id]
    if not include_done:
        query += " AND status = 'pending'"
    query += " ORDER BY day, id"
    return [Task(**row) for row in conn.execute(query, params)]


def list_known_tags(conn: sqlite3.Connection) -> list[str]:
    """Tags distintas já usadas, em ordem alfabética."""
    known: set[str] = set()
    for row in conn.execute("SELECT tags FROM tasks WHERE tags IS NOT NULL"):
        known.update(row["tags"].split(","))
    return sorted(known)


# --- Projetos ---------------------------------------------------------------


def add_project(
    conn: sqlite3.Connection, name: str, goal: str, deadline: str | None = None
) -> Project:
    cur = conn.execute(
        "INSERT INTO projects (name, goal, deadline, created_at) VALUES (?, ?, ?, ?)",
        (name, goal, validate_date(deadline, "prazo"), _now()),
    )
    conn.commit()
    return get_project(conn, cur.lastrowid)


def get_project(conn: sqlite3.Connection, project_id: int) -> Project:
    row = conn.execute(f"SELECT {PROJECT_COLUMNS} FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        raise LookupError(f"Projeto #{project_id} não encontrado")
    return Project(**row)


def find_project(conn: sqlite3.Connection, ref: str) -> Project:
    """Busca projeto por id numérico ou por nome (case-insensitive)."""
    if ref.isdigit():
        return get_project(conn, int(ref))
    row = conn.execute(
        f"SELECT {PROJECT_COLUMNS} FROM projects WHERE lower(name) = lower(?)", (ref,)
    ).fetchone()
    if row is None:
        raise LookupError(f"Projeto '{ref}' não encontrado")
    return Project(**row)


def list_projects(conn: sqlite3.Connection, include_done: bool = False) -> list[Project]:
    query = f"SELECT {PROJECT_COLUMNS} FROM projects"
    if not include_done:
        query += " WHERE status = 'active'"
    query += " ORDER BY id"
    return [Project(**row) for row in conn.execute(query)]


def set_project_deadline(
    conn: sqlite3.Connection, project_id: int, deadline: str | None
) -> Project:
    get_project(conn, project_id)
    conn.execute(
        "UPDATE projects SET deadline = ? WHERE id = ?",
        (validate_date(deadline, "prazo"), project_id),
    )
    conn.commit()
    return get_project(conn, project_id)


def complete_project(conn: sqlite3.Connection, project_id: int) -> Project:
    get_project(conn, project_id)
    conn.execute("UPDATE projects SET status = 'done' WHERE id = ?", (project_id,))
    conn.commit()
    return get_project(conn, project_id)


# --- Checkpoints ------------------------------------------------------------


def add_checkpoint(
    conn: sqlite3.Connection,
    project_id: int,
    progress: str,
    assessment: str,
    status: str | None = None,
    summary: str | None = None,
) -> Checkpoint:
    get_project(conn, project_id)
    cur = conn.execute(
        "INSERT INTO checkpoints (project_id, progress, assessment, status, summary, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (project_id, progress, assessment, status, summary, _now()),
    )
    conn.commit()
    row = conn.execute(f"SELECT {CHECKPOINT_COLUMNS} FROM checkpoints WHERE id = ?", (cur.lastrowid,)).fetchone()
    return Checkpoint(**row)


def list_checkpoints(conn: sqlite3.Connection, project_id: int) -> list[Checkpoint]:
    rows = conn.execute(
        f"SELECT {CHECKPOINT_COLUMNS} FROM checkpoints WHERE project_id = ? ORDER BY id", (project_id,)
    )
    return [Checkpoint(**row) for row in rows]
