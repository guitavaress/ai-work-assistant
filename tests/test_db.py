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
