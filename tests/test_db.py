import pytest

from work_assistant import db


@pytest.fixture
def conn(tmp_path):
    return db.connect(tmp_path / "test.db")


def test_add_and_list_tasks(conn):
    task = db.add_task(conn, "Revisar PR do serviço de pagamentos", priority=1)
    assert task.id == 1
    assert task.status == "pending"
    assert task.day == db.today()

    tasks = db.list_tasks(conn)
    assert [t.title for t in tasks] == ["Revisar PR do serviço de pagamentos"]


def test_complete_task(conn):
    task = db.add_task(conn, "Escrever testes")
    done = db.complete_task(conn, task.id)
    assert done.status == "done"
    assert done.done_at is not None

    pendentes = db.list_tasks(conn, include_done=False)
    assert pendentes == []


def test_reopen_task(conn):
    task = db.add_task(conn, "Voltar atrás")
    db.complete_task(conn, task.id)
    reopened = db.reopen_task(conn, task.id)
    assert reopened.status == "pending"
    assert reopened.done_at is None


def test_complete_missing_task_raises(conn):
    with pytest.raises(LookupError):
        db.complete_task(conn, 999)


def test_task_ordering_by_priority(conn):
    db.add_task(conn, "sem prioridade")
    db.add_task(conn, "prio 2", priority=2)
    db.add_task(conn, "prio 1", priority=1)
    titles = [t.title for t in db.list_tasks(conn)]
    assert titles == ["prio 1", "prio 2", "sem prioridade"]


def test_tasks_between(conn):
    db.add_task(conn, "ontem", day="2026-07-15")
    db.add_task(conn, "hoje", day="2026-07-16")
    db.add_task(conn, "semana passada", day="2026-07-08")
    tasks = db.list_tasks_between(conn, "2026-07-15", "2026-07-16")
    assert [t.title for t in tasks] == ["ontem", "hoje"]


def test_projects_and_find(conn):
    p = db.add_project(conn, "Faturamento", "Migrar cobrança para o novo gateway até o fim da sprint 12")
    assert db.find_project(conn, "faturamento").id == p.id
    assert db.find_project(conn, str(p.id)).id == p.id
    with pytest.raises(LookupError):
        db.find_project(conn, "inexistente")


def test_complete_project_excluded_from_active_list(conn):
    p = db.add_project(conn, "Legado", "Desligar o serviço legado")
    db.complete_project(conn, p.id)
    assert db.list_projects(conn) == []
    assert len(db.list_projects(conn, include_done=True)) == 1


def test_checkpoints(conn):
    p = db.add_project(conn, "API v2", "Publicar a API v2 com autenticação")
    db.add_checkpoint(conn, p.id, "Endpoints prontos, falta auth", "Em risco: auth não começou")
    cps = db.list_checkpoints(conn, p.id)
    assert len(cps) == 1
    assert "auth" in cps[0].progress

    with pytest.raises(LookupError):
        db.add_checkpoint(conn, 999, "x", "y")


def test_checkpoint_status_and_summary(conn):
    p = db.add_project(conn, "API v2", "Publicar a API v2 com autenticação")
    cp = db.add_checkpoint(
        conn, p.id, "relato", "avaliação", status="em risco", summary="Em risco — auth parada."
    )
    assert cp.status == "em risco"
    assert cp.summary == "Em risco — auth parada."


def test_migration_adds_checkpoint_columns(tmp_path):
    """Banco criado com o schema antigo (sem status/summary) ganha as colunas no connect()."""
    import sqlite3

    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript(
        """
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
            goal TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL
        );
        CREATE TABLE checkpoints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL REFERENCES projects(id),
            progress TEXT NOT NULL, assessment TEXT NOT NULL, created_at TEXT NOT NULL
        );
        INSERT INTO projects (name, goal, created_at) VALUES ('X', 'meta', '2026-01-01');
        INSERT INTO checkpoints (project_id, progress, assessment, created_at)
            VALUES (1, 'antigo', 'ok', '2026-01-01');
        """
    )
    old.commit()
    old.close()

    conn = db.connect(path)
    cps = db.list_checkpoints(conn, 1)
    assert cps[0].status is None
    assert cps[0].summary is None
    db.add_checkpoint(conn, 1, "novo", "ok", status="no rumo", summary="No rumo.")
    assert db.list_checkpoints(conn, 1)[-1].status == "no rumo"
