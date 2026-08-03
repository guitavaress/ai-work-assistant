"""Persistência em SQLite: tarefas, projetos, etapas, rotinas e checkpoints."""

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from work_assistant import config, schedule

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    goal TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',  -- active | done
    deadline TEXT,                          -- data-alvo da entrega (YYYY-MM-DD)
    kind TEXT NOT NULL DEFAULT 'project',   -- project | routine_run (ciclo de uma rotina)
    routine_id INTEGER REFERENCES routines(id),  -- preenchido só em routine_run
    period TEXT,                            -- período do ciclo: 'YYYY-MM', 'YYYY-Www' ou 'YYYY-MM-DD'
    created_at TEXT NOT NULL,
    done_at TEXT                            -- quando foi concluído (NULL em registros antigos)
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
    stage_id INTEGER REFERENCES stages(id),  -- etapa do projeto (opcional)
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
    stage_id INTEGER REFERENCES stages(id),  -- etapa avaliada (opcional)
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    name TEXT NOT NULL,
    position INTEGER NOT NULL,               -- ordem da etapa dentro do projeto (1..n)
    deadline TEXT,                           -- data-alvo da etapa (YYYY-MM-DD)
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | done
    done_criteria TEXT,                      -- critério de pronto (o que precisa ser verdade)
    created_at TEXT NOT NULL,
    done_at TEXT
);

CREATE TABLE IF NOT EXISTS routines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    goal TEXT NOT NULL,                      -- o que significa "a rotina rodou bem"
    cadence TEXT NOT NULL,                   -- monthly | weekly
    anchor INTEGER NOT NULL,                 -- mensal: dia 1..31 ou -1..-28 (do fim do mês)
                                             -- semanal: dia ISO 1..7 (1 = segunda)
    sla_days INTEGER NOT NULL DEFAULT 1,     -- duração da janela em dias, contando o
                                             -- dia de abertura (abre 1, fecha 5 = 5)
    status TEXT NOT NULL DEFAULT 'active',   -- active | archived
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS checkpoint_verdicts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    checkpoint_id INTEGER NOT NULL REFERENCES checkpoints(id),
    stage_id INTEGER NOT NULL REFERENCES stages(id),
    verdict TEXT NOT NULL,     -- atende | nao_atende | nao_avaliada
    rationale TEXT,            -- justificativa curta do modelo
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS routine_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    routine_id INTEGER NOT NULL REFERENCES routines(id),
    name TEXT NOT NULL,
    position INTEGER NOT NULL,
    offset_days INTEGER NOT NULL DEFAULT 0,  -- prazo da etapa = abertura do ciclo + offset_days
    done_criteria TEXT,
    created_at TEXT NOT NULL
);
"""

# Índices ficam FORA do SCHEMA de propósito: connect() roda o SCHEMA antes de _migrate(),
# e estes índices referenciam colunas que só existem depois do ALTER TABLE. Criá-los junto
# do SCHEMA quebraria connect() em qualquer banco anterior a esta versão.
INDEXES = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_routine_period
    ON projects(routine_id, period) WHERE routine_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_stages_project ON stages(project_id, position);
CREATE INDEX IF NOT EXISTS idx_tasks_stage ON tasks(stage_id);
CREATE INDEX IF NOT EXISTS idx_routine_steps_routine ON routine_steps(routine_id, position);
CREATE INDEX IF NOT EXISTS idx_verdicts_checkpoint ON checkpoint_verdicts(checkpoint_id);
CREATE INDEX IF NOT EXISTS idx_verdicts_stage ON checkpoint_verdicts(stage_id, id);
"""

# Colunas adicionadas depois do schema inicial: bancos existentes precisam de ALTER.
_MIGRATIONS = {
    "checkpoints": {
        "status": "ALTER TABLE checkpoints ADD COLUMN status TEXT",
        "summary": "ALTER TABLE checkpoints ADD COLUMN summary TEXT",
        "stage_id": "ALTER TABLE checkpoints ADD COLUMN stage_id INTEGER REFERENCES stages(id)",
    },
    "tasks": {
        "due_date": "ALTER TABLE tasks ADD COLUMN due_date TEXT",
        "tags": "ALTER TABLE tasks ADD COLUMN tags TEXT",
        "source": "ALTER TABLE tasks ADD COLUMN source TEXT NOT NULL DEFAULT 'manual'",
        "effort": "ALTER TABLE tasks ADD COLUMN effort TEXT",
        "stage_id": "ALTER TABLE tasks ADD COLUMN stage_id INTEGER REFERENCES stages(id)",
    },
    "projects": {
        "deadline": "ALTER TABLE projects ADD COLUMN deadline TEXT",
        "kind": "ALTER TABLE projects ADD COLUMN kind TEXT NOT NULL DEFAULT 'project'",
        "routine_id": "ALTER TABLE projects ADD COLUMN routine_id INTEGER REFERENCES routines(id)",
        "period": "ALTER TABLE projects ADD COLUMN period TEXT",
        "done_at": "ALTER TABLE projects ADD COLUMN done_at TEXT",
    },
}

# Versão do ESQUEMA DE DADO deste pacote, guardada no `PRAGMA user_version` do
# arquivo .db. Atenção: o pragma é global do arquivo, que é compartilhado com
# outras branches (ver comentário das constantes de coluna abaixo).
#   1 — sla_days passou de deslocamento para duração da janela.
SCHEMA_VERSION = 1

EFFORT_LEVELS = ("P", "M", "G")
STAGE_STATUSES = ("pending", "done")
# Valores em ASCII porque o enum vira gramática GBNF no llm.structured();
# a acentuação vive só na exibição (VERDICT_LABELS).
VERDICT_VALUES = ("atende", "nao_atende", "nao_avaliada")
VERDICT_LABELS = {
    "atende": "atende",
    "nao_atende": "não atende",
    "nao_avaliada": "não avaliada",
}
# Um projeto normal é uma entrega finita; um routine_run é o ciclo materializado de
# uma rotina (ex.: "Janela de Comissões — 2026-08") e reaproveita toda a máquina de
# etapas, tarefas e checkpoints.
PROJECT_KINDS = ("project", "routine_run")

# Colunas explícitas (em vez de SELECT *) para não quebrar a construção das dataclasses
# quando o arquivo .db tem colunas extras vindas de outra branch (ex.: azdo-integration,
# que roda contra o mesmo ~/.ai-work-assistant/assistant.db e adiciona `external_ref`).
TASK_COLUMNS = (
    "id, title, project_id, day, status, priority, created_at, done_at,"
    " due_date, tags, source, effort, stage_id"
)
PROJECT_COLUMNS = (
    "id, name, goal, status, created_at, deadline, kind, routine_id, period, done_at"
)
CHECKPOINT_COLUMNS = (
    "id, project_id, progress, assessment, status, summary, created_at, stage_id"
)
STAGE_COLUMNS = (
    "id, project_id, name, position, deadline, status, done_criteria, created_at, done_at"
)
ROUTINE_COLUMNS = "id, name, goal, cadence, anchor, sla_days, status, created_at"
ROUTINE_STEP_COLUMNS = (
    "id, routine_id, name, position, offset_days, done_criteria, created_at"
)
VERDICT_COLUMNS = "id, checkpoint_id, stage_id, verdict, rationale, created_at"


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
    stage_id: int | None = None


@dataclass
class Project:
    id: int
    name: str
    goal: str
    status: str
    created_at: str
    deadline: str | None = None
    kind: str = "project"
    routine_id: int | None = None
    period: str | None = None
    done_at: str | None = None


@dataclass
class Checkpoint:
    id: int
    project_id: int
    progress: str
    assessment: str
    status: str | None
    summary: str | None
    created_at: str
    stage_id: int | None = None


@dataclass
class Stage:
    id: int
    project_id: int
    name: str
    position: int
    deadline: str | None
    status: str
    done_criteria: str | None
    created_at: str
    done_at: str | None = None


@dataclass
class CheckpointVerdict:
    id: int
    checkpoint_id: int
    stage_id: int
    verdict: str
    rationale: str | None
    created_at: str


@dataclass
class Routine:
    id: int
    name: str
    goal: str
    cadence: str
    anchor: int
    sla_days: int
    status: str
    created_at: str


@dataclass
class RoutineStep:
    id: int
    routine_id: int
    name: str
    position: int
    offset_days: int
    done_criteria: str | None
    created_at: str


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.executescript(INDEXES)  # depois do _migrate: dependem das colunas novas
    _migrate_data(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    for table, columns in _MIGRATIONS.items():
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        for column, ddl in columns.items():
            if column not in existing:
                conn.execute(ddl)
    conn.commit()


def _migrate_data(conn: sqlite3.Connection) -> None:
    """Migrações que transformam DADO, não estrutura.

    `_MIGRATIONS` é keyed por coluna ausente (`PRAGMA table_info`), então só serve
    para criar coluna: uma transformação ali rodaria de novo a cada `connect()`.
    O contador é o `PRAGMA user_version` do próprio SQLite.
    """
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version < 1:
        # v1: sla_days deixou de ser deslocamento e virou duração da janela,
        # contando o dia de abertura (abre dia 1, fecha dia 5 = 5).
        conn.execute("UPDATE routines SET sla_days = sla_days + 1")
    if version < SCHEMA_VERSION:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")  # não aceita bind
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
    stage_id: int | None = None,
) -> Task:
    if stage_id is not None:
        # A etapa manda: o projeto vem dela (ver invariante em set_task_stage).
        project_id = get_stage(conn, stage_id).project_id
    elif project_id is not None:
        get_project(conn, project_id)
    cur = conn.execute(
        "INSERT INTO tasks (title, project_id, day, priority, due_date, tags, source, effort,"
        " stage_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            title,
            project_id,
            day or today(),
            priority,
            validate_date(due_date, "prazo"),
            normalize_tags(tags),
            source,
            validate_effort(effort),
            stage_id,
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
    """Move a tarefa de projeto, largando a etapa se ela era de outro projeto."""
    task = get_task(conn, task_id)
    if project_id is not None:
        get_project(conn, project_id)
    stage_id = task.stage_id
    if stage_id is not None and get_stage(conn, stage_id).project_id != project_id:
        stage_id = None
    conn.execute(
        "UPDATE tasks SET project_id = ?, stage_id = ? WHERE id = ?",
        (project_id, stage_id, task_id),
    )
    conn.commit()
    return get_task(conn, task_id)


def set_task_stage(conn: sqlite3.Connection, task_id: int, stage_id: int | None) -> Task:
    """Vincula a tarefa a uma etapa; o projeto passa a ser o da etapa.

    Invariante: `stage_id` preenchido implica `project_id` igual ao da etapa, então
    `(project_id, stage_id)` nunca fica inconsistente. Passar None solta a etapa e
    mantém o projeto.
    """
    get_task(conn, task_id)
    if stage_id is None:
        conn.execute("UPDATE tasks SET stage_id = NULL WHERE id = ?", (task_id,))
    else:
        stage = get_stage(conn, stage_id)
        conn.execute(
            "UPDATE tasks SET stage_id = ?, project_id = ? WHERE id = ?",
            (stage.id, stage.project_id, task_id),
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


def list_tasks_by_stage(
    conn: sqlite3.Connection, stage_id: int, include_done: bool = True
) -> list[Task]:
    query = f"SELECT {TASK_COLUMNS} FROM tasks WHERE stage_id = ?"
    params: list = [stage_id]
    if not include_done:
        query += " AND status = 'pending'"
    query += " ORDER BY day, id"
    return [Task(**row) for row in conn.execute(query, params)]


def _task_counts(conn: sqlite3.Connection, column: str, value: int) -> dict:
    row = conn.execute(
        f"SELECT COUNT(*) AS total, COALESCE(SUM(status = 'done'), 0) AS done"
        f" FROM tasks WHERE {column} = ?",
        (value,),
    ).fetchone()
    return {"total": row["total"], "done": row["done"]}


def project_progress(conn: sqlite3.Connection, project_id: int) -> dict:
    """Contagem canônica de tarefas do projeto: {'total': n, 'done': n}."""
    return _task_counts(conn, "project_id", project_id)


def stage_progress(conn: sqlite3.Connection, stage_id: int) -> dict:
    return _task_counts(conn, "stage_id", stage_id)


def stage_progress_map(conn: sqlite3.Connection, project_id: int) -> dict[int, dict]:
    """Progresso de todas as etapas do projeto num único GROUP BY.

    `stage_progress` é uma query por etapa; montar a tela inteira com ela daria
    dezenas de consultas por request.
    """
    rows = conn.execute(
        "SELECT s.id AS stage_id, COUNT(t.id) AS total,"
        " COALESCE(SUM(t.status = 'done'), 0) AS done"
        " FROM stages s LEFT JOIN tasks t ON t.stage_id = s.id"
        " WHERE s.project_id = ? GROUP BY s.id",
        (project_id,),
    )
    return {row["stage_id"]: {"total": row["total"], "done": row["done"]} for row in rows}


def stage_names(conn: sqlite3.Connection) -> dict[int, str]:
    """Nome de toda etapa, para resolver o rótulo da tarefa sem N+1."""
    return {row["id"]: row["name"] for row in conn.execute("SELECT id, name FROM stages")}


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


def list_projects(
    conn: sqlite3.Connection, include_done: bool = False, kind: str | None = "project"
) -> list[Project]:
    """Lista projetos. Por padrão só entregas próprias — ciclos de rotina ficam de fora.

    Passe `kind=None` para incluir os ciclos (usado por quem monta mapa de nomes) ou
    `kind='routine_run'` para ver só eles.
    """
    query = f"SELECT {PROJECT_COLUMNS} FROM projects"
    clauses = []
    params: list = []
    if not include_done:
        clauses.append("status = 'active'")
    if kind is not None:
        clauses.append("kind = ?")
        params.append(kind)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY id"
    return [Project(**row) for row in conn.execute(query, params)]


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


def complete_project(
    conn: sqlite3.Connection, project_id: int, closed_on: str | None = None
) -> Project:
    """Conclui o projeto/ciclo, gravando quando fechou.

    `closed_on` (YYYY-MM-DD) permite registrar um fechamento retroativo — é o que
    dá para corrigir à mão um ciclo que o usuário fechou fora do app.
    """
    get_project(conn, project_id)
    when = f"{validate_date(closed_on, 'data de fechamento')}T00:00:00" if closed_on else _now()
    conn.execute(
        "UPDATE projects SET status = 'done', done_at = ? WHERE id = ?", (when, project_id)
    )
    conn.commit()
    return get_project(conn, project_id)


def reopen_project(conn: sqlite3.Connection, project_id: int) -> Project:
    get_project(conn, project_id)
    conn.execute(
        "UPDATE projects SET status = 'active', done_at = NULL WHERE id = ?", (project_id,)
    )
    conn.commit()
    return get_project(conn, project_id)


# --- Etapas -----------------------------------------------------------------


def add_stage(
    conn: sqlite3.Connection,
    project_id: int,
    name: str,
    deadline: str | None = None,
    done_criteria: str | None = None,
    position: int | None = None,
) -> Stage:
    """Cria uma etapa no projeto. Sem `position`, entra no fim da fila."""
    get_project(conn, project_id)
    last = conn.execute(
        "SELECT COALESCE(MAX(position), 0) AS last FROM stages WHERE project_id = ?",
        (project_id,),
    ).fetchone()["last"]
    if position is None:
        position = last + 1
    else:
        position = max(1, min(position, last + 1))
        # Abre espaço empurrando as etapas seguintes.
        conn.execute(
            "UPDATE stages SET position = position + 1 WHERE project_id = ? AND position >= ?",
            (project_id, position),
        )
    cur = conn.execute(
        "INSERT INTO stages (project_id, name, position, deadline, done_criteria, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (project_id, name, position, validate_date(deadline, "prazo"), done_criteria, _now()),
    )
    conn.commit()
    return get_stage(conn, cur.lastrowid)


def get_stage(conn: sqlite3.Connection, stage_id: int) -> Stage:
    row = conn.execute(
        f"SELECT {STAGE_COLUMNS} FROM stages WHERE id = ?", (stage_id,)
    ).fetchone()
    if row is None:
        raise LookupError(f"Etapa #{stage_id} não encontrada")
    return Stage(**row)


def find_stage(conn: sqlite3.Connection, project_id: int, ref: str) -> Stage:
    """Busca etapa do projeto por posição, id ou nome (case-insensitive).

    Número é lido primeiro como posição — é o que a CLI mostra na coluna `#`.
    """
    if ref.isdigit():
        for column in ("position", "id"):
            row = conn.execute(
                f"SELECT {STAGE_COLUMNS} FROM stages WHERE project_id = ? AND {column} = ?",
                (project_id, int(ref)),
            ).fetchone()
            if row is not None:
                return Stage(**row)
    else:
        row = conn.execute(
            f"SELECT {STAGE_COLUMNS} FROM stages WHERE project_id = ? AND lower(name) = lower(?)",
            (project_id, ref),
        ).fetchone()
        if row is not None:
            return Stage(**row)
    raise LookupError(f"Etapa '{ref}' não encontrada no projeto #{project_id}")


def list_stages(
    conn: sqlite3.Connection, project_id: int, include_done: bool = True
) -> list[Stage]:
    query = f"SELECT {STAGE_COLUMNS} FROM stages WHERE project_id = ?"
    params: list = [project_id]
    if not include_done:
        query += " AND status = 'pending'"
    query += " ORDER BY position, id"
    return [Stage(**row) for row in conn.execute(query, params)]


def set_stage_deadline(
    conn: sqlite3.Connection, stage_id: int, deadline: str | None
) -> Stage:
    get_stage(conn, stage_id)
    conn.execute(
        "UPDATE stages SET deadline = ? WHERE id = ?",
        (validate_date(deadline, "prazo"), stage_id),
    )
    conn.commit()
    return get_stage(conn, stage_id)


def set_stage_criteria(
    conn: sqlite3.Connection, stage_id: int, done_criteria: str | None
) -> Stage:
    get_stage(conn, stage_id)
    conn.execute(
        "UPDATE stages SET done_criteria = ? WHERE id = ?", (done_criteria, stage_id)
    )
    conn.commit()
    return get_stage(conn, stage_id)


def complete_stage(conn: sqlite3.Connection, stage_id: int) -> Stage:
    get_stage(conn, stage_id)
    conn.execute(
        "UPDATE stages SET status = 'done', done_at = ? WHERE id = ?", (_now(), stage_id)
    )
    conn.commit()
    return get_stage(conn, stage_id)


def reopen_stage(conn: sqlite3.Connection, stage_id: int) -> Stage:
    get_stage(conn, stage_id)
    conn.execute(
        "UPDATE stages SET status = 'pending', done_at = NULL WHERE id = ?", (stage_id,)
    )
    conn.commit()
    return get_stage(conn, stage_id)


# --- Checkpoints ------------------------------------------------------------


def add_checkpoint(
    conn: sqlite3.Connection,
    project_id: int,
    progress: str,
    assessment: str,
    status: str | None = None,
    summary: str | None = None,
    stage_id: int | None = None,
) -> Checkpoint:
    get_project(conn, project_id)
    if stage_id is not None and get_stage(conn, stage_id).project_id != project_id:
        raise ValueError(f"Etapa #{stage_id} não pertence ao projeto #{project_id}")
    cur = conn.execute(
        "INSERT INTO checkpoints (project_id, progress, assessment, status, summary, stage_id,"
        " created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (project_id, progress, assessment, status, summary, stage_id, _now()),
    )
    conn.commit()
    row = conn.execute(f"SELECT {CHECKPOINT_COLUMNS} FROM checkpoints WHERE id = ?", (cur.lastrowid,)).fetchone()
    return Checkpoint(**row)


def list_checkpoints(conn: sqlite3.Connection, project_id: int) -> list[Checkpoint]:
    rows = conn.execute(
        f"SELECT {CHECKPOINT_COLUMNS} FROM checkpoints WHERE project_id = ? ORDER BY id", (project_id,)
    )
    return [Checkpoint(**row) for row in rows]


# --- Vereditos por etapa ----------------------------------------------------


def validate_verdict(verdict: str) -> str:
    if verdict not in VERDICT_VALUES:
        raise ValueError(
            f"Veredito inválido '{verdict}': use {', '.join(VERDICT_VALUES)}"
        )
    return verdict


def add_checkpoint_verdicts(
    conn: sqlite3.Connection, checkpoint_id: int, verdicts: list[dict]
) -> list[CheckpointVerdict]:
    """Grava o veredito do modelo para cada etapa avaliada no checkpoint.

    Cada item: {"stage_id": int, "verdict": str, "rationale": str | None}.
    """
    row = conn.execute(
        "SELECT project_id FROM checkpoints WHERE id = ?", (checkpoint_id,)
    ).fetchone()
    if row is None:
        raise LookupError(f"Checkpoint #{checkpoint_id} não encontrado")
    project_id = row["project_id"]
    for item in verdicts:
        stage = get_stage(conn, item["stage_id"])
        if stage.project_id != project_id:
            raise ValueError(
                f"Etapa #{stage.id} não pertence ao projeto #{project_id}"
            )
        conn.execute(
            "INSERT INTO checkpoint_verdicts (checkpoint_id, stage_id, verdict, rationale,"
            " created_at) VALUES (?, ?, ?, ?, ?)",
            (
                checkpoint_id,
                stage.id,
                validate_verdict(item["verdict"]),
                item.get("rationale"),
                _now(),
            ),
        )
    conn.commit()
    return list_checkpoint_verdicts(conn, checkpoint_id)


def list_checkpoint_verdicts(
    conn: sqlite3.Connection, checkpoint_id: int
) -> list[CheckpointVerdict]:
    rows = conn.execute(
        f"SELECT {VERDICT_COLUMNS} FROM checkpoint_verdicts WHERE checkpoint_id = ?"
        " ORDER BY id",
        (checkpoint_id,),
    )
    return [CheckpointVerdict(**row) for row in rows]


def last_stage_verdicts(
    conn: sqlite3.Connection, project_id: int
) -> dict[int, CheckpointVerdict]:
    """Veredito mais recente de cada etapa do projeto, indexado por stage_id."""
    rows = conn.execute(
        f"SELECT {VERDICT_COLUMNS} FROM checkpoint_verdicts"
        " WHERE stage_id IN (SELECT id FROM stages WHERE project_id = ?) ORDER BY id",
        (project_id,),
    )
    # ORDER BY id crescente + sobrescrita: sobra o último veredito de cada etapa.
    return {row["stage_id"]: CheckpointVerdict(**row) for row in rows}


# --- Rotinas ----------------------------------------------------------------


def add_routine(
    conn: sqlite3.Connection,
    name: str,
    goal: str,
    cadence: str,
    anchor: int,
    sla_days: int = 1,
) -> Routine:
    cadence = schedule.validate_cadence(cadence)
    anchor = schedule.validate_anchor(cadence, anchor)
    if sla_days < 1:
        raise ValueError(
            f"SLA inválido '{sla_days}': a janela tem no mínimo 1 dia"
            " (é a duração contando o dia de abertura)"
        )
    cur = conn.execute(
        "INSERT INTO routines (name, goal, cadence, anchor, sla_days, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (name, goal, cadence, anchor, sla_days, _now()),
    )
    conn.commit()
    return get_routine(conn, cur.lastrowid)


def get_routine(conn: sqlite3.Connection, routine_id: int) -> Routine:
    row = conn.execute(
        f"SELECT {ROUTINE_COLUMNS} FROM routines WHERE id = ?", (routine_id,)
    ).fetchone()
    if row is None:
        raise LookupError(f"Rotina #{routine_id} não encontrada")
    return Routine(**row)


def find_routine(conn: sqlite3.Connection, ref: str) -> Routine:
    """Busca rotina por id numérico ou por nome (case-insensitive)."""
    if ref.isdigit():
        return get_routine(conn, int(ref))
    row = conn.execute(
        f"SELECT {ROUTINE_COLUMNS} FROM routines WHERE lower(name) = lower(?)", (ref,)
    ).fetchone()
    if row is None:
        raise LookupError(f"Rotina '{ref}' não encontrada")
    return Routine(**row)


def list_routines(conn: sqlite3.Connection, include_archived: bool = False) -> list[Routine]:
    query = f"SELECT {ROUTINE_COLUMNS} FROM routines"
    if not include_archived:
        query += " WHERE status = 'active'"
    query += " ORDER BY id"
    return [Routine(**row) for row in conn.execute(query)]


def archive_routine(conn: sqlite3.Connection, routine_id: int) -> Routine:
    get_routine(conn, routine_id)
    conn.execute("UPDATE routines SET status = 'archived' WHERE id = ?", (routine_id,))
    conn.commit()
    return get_routine(conn, routine_id)


def add_routine_step(
    conn: sqlite3.Connection,
    routine_id: int,
    name: str,
    offset_days: int = 0,
    done_criteria: str | None = None,
    position: int | None = None,
) -> RoutineStep:
    get_routine(conn, routine_id)
    if position is None:
        position = conn.execute(
            "SELECT COALESCE(MAX(position), 0) + 1 AS next FROM routine_steps WHERE routine_id = ?",
            (routine_id,),
        ).fetchone()["next"]
    cur = conn.execute(
        "INSERT INTO routine_steps (routine_id, name, position, offset_days, done_criteria,"
        " created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (routine_id, name, position, offset_days, done_criteria, _now()),
    )
    conn.commit()
    row = conn.execute(
        f"SELECT {ROUTINE_STEP_COLUMNS} FROM routine_steps WHERE id = ?", (cur.lastrowid,)
    ).fetchone()
    return RoutineStep(**row)


def list_routine_steps(conn: sqlite3.Connection, routine_id: int) -> list[RoutineStep]:
    rows = conn.execute(
        f"SELECT {ROUTINE_STEP_COLUMNS} FROM routine_steps WHERE routine_id = ?"
        " ORDER BY position, id",
        (routine_id,),
    )
    return [RoutineStep(**row) for row in rows]


def replace_routine_steps(
    conn: sqlite3.Connection, routine_id: int, steps: list[dict]
) -> list[RoutineStep]:
    """Troca o checklist inteiro; a ordem da lista vira a `position`.

    Só afeta ciclos futuros: os ciclos já materializados guardam cópia das etapas.
    """
    get_routine(conn, routine_id)
    conn.execute("DELETE FROM routine_steps WHERE routine_id = ?", (routine_id,))
    for position, step in enumerate(steps, 1):
        conn.execute(
            "INSERT INTO routine_steps (routine_id, name, position, offset_days,"
            " done_criteria, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                routine_id,
                step["name"],
                position,
                step.get("offset_days", 0),
                step.get("done_criteria"),
                _now(),
            ),
        )
    conn.commit()
    return list_routine_steps(conn, routine_id)


def delete_routine_step(conn: sqlite3.Connection, step_id: int) -> None:
    conn.execute("DELETE FROM routine_steps WHERE id = ?", (step_id,))
    conn.commit()


# --- Ciclos de rotina (linhas de projects com kind='routine_run') ------------


def add_routine_run(
    conn: sqlite3.Connection,
    routine_id: int,
    period: str,
    name: str,
    goal: str,
    deadline: str | None = None,
) -> Project:
    """Cria o ciclo de um período. O índice único (routine_id, period) impede duplicata."""
    get_routine(conn, routine_id)
    cur = conn.execute(
        "INSERT INTO projects (name, goal, deadline, kind, routine_id, period, created_at)"
        " VALUES (?, ?, ?, 'routine_run', ?, ?, ?)",
        (name, goal, validate_date(deadline, "prazo"), routine_id, period, _now()),
    )
    conn.commit()
    return get_project(conn, cur.lastrowid)


def find_routine_run(
    conn: sqlite3.Connection, routine_id: int, period: str
) -> Project | None:
    row = conn.execute(
        f"SELECT {PROJECT_COLUMNS} FROM projects WHERE routine_id = ? AND period = ?",
        (routine_id, period),
    ).fetchone()
    return Project(**row) if row else None


def list_routine_runs_due_between(
    conn: sqlite3.Connection, start: str, end: str
) -> list[Project]:
    """Ciclos cujo prazo cai na janela — é o prazo que define o evento de SLA."""
    rows = conn.execute(
        f"SELECT {PROJECT_COLUMNS} FROM projects WHERE kind = 'routine_run'"
        " AND deadline IS NOT NULL AND deadline BETWEEN ? AND ? ORDER BY deadline, id",
        (start, end),
    )
    return [Project(**row) for row in rows]


def count_stages_done_between(conn: sqlite3.Connection, start: str, end: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM stages WHERE status = 'done'"
        " AND done_at IS NOT NULL AND substr(done_at, 1, 10) BETWEEN ? AND ?",
        (start, end),
    ).fetchone()
    return row["n"]


def list_routine_runs(
    conn: sqlite3.Connection, routine_id: int, include_done: bool = True
) -> list[Project]:
    query = f"SELECT {PROJECT_COLUMNS} FROM projects WHERE routine_id = ?"
    params: list = [routine_id]
    if not include_done:
        query += " AND status = 'active'"
    query += " ORDER BY period"
    return [Project(**row) for row in conn.execute(query, params)]
