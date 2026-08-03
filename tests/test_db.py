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


def test_task_due_tags_effort(conn):
    task = db.add_task(
        conn, "Corrigir pipeline", due_date="2030-01-05", tags=["Bug", "dados "], effort="m"
    )
    assert task.due_date == "2030-01-05"
    assert task.tags == "bug,dados"
    assert task.effort == "M"
    assert task.source == "manual"


def test_normalize_tags_accepts_csv_and_dedupes():
    assert db.normalize_tags("Bug, dados, bug") == "bug,dados"
    assert db.normalize_tags(["", "  "]) is None
    assert db.normalize_tags(None) is None


def test_invalid_effort_and_date_raise(conn):
    with pytest.raises(ValueError):
        db.add_task(conn, "x", effort="XG")
    with pytest.raises(ValueError):
        db.add_task(conn, "x", due_date="05/01/2030")


def test_set_task_due_and_tags(conn):
    task = db.add_task(conn, "Ajustar job")
    assert db.set_task_due(conn, task.id, "2030-02-01").due_date == "2030-02-01"
    assert db.set_task_tags(conn, task.id, "pipeline, dados").tags == "pipeline,dados"
    assert db.set_task_due(conn, task.id, None).due_date is None


def test_list_known_tags(conn):
    db.add_task(conn, "a", tags="bug,dados")
    db.add_task(conn, "b", tags=["reuniao", "bug"])
    assert db.list_known_tags(conn) == ["bug", "dados", "reuniao"]


def test_add_task_with_project(conn):
    p = db.add_project(conn, "API v2", "Publicar API v2")
    task = db.add_task(conn, "Endpoint de auth", project_id=p.id)
    assert task.project_id == p.id
    with pytest.raises(LookupError):
        db.add_task(conn, "x", project_id=999)


def test_set_task_effort(conn):
    task = db.add_task(conn, "Ajustar job")
    assert db.set_task_effort(conn, task.id, "g").effort == "G"
    assert db.set_task_effort(conn, task.id, None).effort is None
    with pytest.raises(ValueError):
        db.set_task_effort(conn, task.id, "XG")


def test_set_task_project(conn):
    p = db.add_project(conn, "API v2", "Publicar API v2")
    task = db.add_task(conn, "sem projeto")
    updated = db.set_task_project(conn, task.id, p.id)
    assert updated.project_id == p.id
    with pytest.raises(LookupError):
        db.set_task_project(conn, task.id, 999)
    cleared = db.set_task_project(conn, task.id, None)
    assert cleared.project_id is None


def test_list_tasks_by_project(conn):
    p = db.add_project(conn, "API v2", "Publicar API v2")
    other = db.add_project(conn, "Outro", "meta")
    db.add_task(conn, "ontem", day="2026-07-15", project_id=p.id)
    db.add_task(conn, "hoje", day="2026-07-16", project_id=p.id)
    db.add_task(conn, "de outro projeto", project_id=other.id)
    tasks = db.list_tasks_by_project(conn, p.id)
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


def test_project_deadline(conn):
    p = db.add_project(conn, "Faturamento", "Migrar cobrança", deadline="2030-03-01")
    assert p.deadline == "2030-03-01"
    updated = db.set_project_deadline(conn, p.id, "2030-04-01")
    assert updated.deadline == "2030-04-01"
    with pytest.raises(ValueError):
        db.add_project(conn, "Outro", "meta", deadline="março")


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


def test_migration_adds_task_and_project_columns(tmp_path):
    """Banco antigo (sem due_date/tags/source/effort/deadline) ganha as colunas no connect()."""
    import sqlite3

    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript(
        """
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
            goal TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL
        );
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
            project_id INTEGER REFERENCES projects(id), day TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending', priority INTEGER,
            created_at TEXT NOT NULL, done_at TEXT
        );
        INSERT INTO projects (name, goal, created_at) VALUES ('X', 'meta', '2026-01-01');
        INSERT INTO tasks (title, day, created_at) VALUES ('antiga', '2026-01-01', '2026-01-01');
        """
    )
    old.commit()
    old.close()

    conn = db.connect(path)
    antiga = db.get_task(conn, 1)
    assert antiga.due_date is None
    assert antiga.tags is None
    assert antiga.source == "manual"
    assert antiga.effort is None
    assert db.get_project(conn, 1).deadline is None

    nova = db.add_task(conn, "nova", due_date="2030-01-01", tags="bug", effort="P")
    assert (nova.due_date, nova.tags, nova.effort) == ("2030-01-01", "bug", "P")
    assert db.set_project_deadline(conn, 1, "2030-06-01").deadline == "2030-06-01"


def test_migration_adds_stage_and_routine_columns(tmp_path):
    """Banco antigo ganha stage_id/kind/routine_id/period e os índices no connect()."""
    import sqlite3

    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript(
        """
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
            goal TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL
        );
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
            project_id INTEGER REFERENCES projects(id), day TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending', priority INTEGER,
            created_at TEXT NOT NULL, done_at TEXT
        );
        CREATE TABLE checkpoints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL REFERENCES projects(id),
            progress TEXT NOT NULL, assessment TEXT NOT NULL, created_at TEXT NOT NULL
        );
        INSERT INTO projects (name, goal, created_at) VALUES ('X', 'meta', '2026-01-01');
        INSERT INTO tasks (title, day, created_at) VALUES ('antiga', '2026-01-01', '2026-01-01');
        INSERT INTO checkpoints (project_id, progress, assessment, created_at)
            VALUES (1, 'antigo', 'ok', '2026-01-01');
        """
    )
    old.commit()
    old.close()

    conn = db.connect(path)
    assert db.get_task(conn, 1).stage_id is None
    assert db.list_checkpoints(conn, 1)[0].stage_id is None

    projeto = db.get_project(conn, 1)
    assert projeto.kind == "project"  # o DEFAULT preenche as linhas que já existiam
    assert projeto.routine_id is None
    assert projeto.period is None
    assert projeto.done_at is None

    # Os índices só podem ser criados depois do ALTER TABLE (ver INDEXES em db.py).
    indexes = {row["name"] for row in conn.execute("PRAGMA index_list(projects)")}
    assert "idx_projects_routine_period" in indexes


# --- Etapas -----------------------------------------------------------------


def test_add_stage_autonumbers_position(conn):
    p = db.add_project(conn, "Janela", "fechar comissões")
    a = db.add_stage(conn, p.id, "Ingestão")
    b = db.add_stage(conn, p.id, "Processamento")
    assert (a.position, b.position) == (1, 2)
    assert a.status == "pending"


def test_add_stage_with_position_shifts_the_rest(conn):
    p = db.add_project(conn, "Janela", "fechar comissões")
    db.add_stage(conn, p.id, "Ingestão")
    db.add_stage(conn, p.id, "Publicação")
    db.add_stage(conn, p.id, "Reconciliação", position=2)
    assert [s.name for s in db.list_stages(conn, p.id)] == [
        "Ingestão",
        "Reconciliação",
        "Publicação",
    ]


def test_find_stage_by_position_id_and_name(conn):
    p = db.add_project(conn, "Janela", "fechar comissões")
    db.add_stage(conn, p.id, "Ingestão")
    alvo = db.add_stage(conn, p.id, "Reconciliação")
    assert db.find_stage(conn, p.id, "2").id == alvo.id  # posição
    assert db.find_stage(conn, p.id, "reconciliação").id == alvo.id
    assert db.find_stage(conn, p.id, str(alvo.id)).id == alvo.id
    with pytest.raises(LookupError):
        db.find_stage(conn, p.id, "inexistente")


def test_stage_deadline_and_criteria(conn):
    p = db.add_project(conn, "Janela", "fechar comissões")
    s = db.add_stage(conn, p.id, "Reconciliação", deadline="2026-08-02")
    assert s.deadline == "2026-08-02"
    assert db.set_stage_criteria(conn, s.id, "diferença < 0,01%").done_criteria == "diferença < 0,01%"
    with pytest.raises(ValueError):
        db.set_stage_deadline(conn, s.id, "agosto")


def test_complete_and_reopen_stage(conn):
    p = db.add_project(conn, "Janela", "fechar comissões")
    s = db.add_stage(conn, p.id, "Ingestão")
    feita = db.complete_stage(conn, s.id)
    assert feita.status == "done" and feita.done_at is not None
    reaberta = db.reopen_stage(conn, s.id)
    assert reaberta.status == "pending" and reaberta.done_at is None


def test_list_stages_excludes_done(conn):
    p = db.add_project(conn, "Janela", "fechar comissões")
    s = db.add_stage(conn, p.id, "Ingestão")
    db.add_stage(conn, p.id, "Reconciliação")
    db.complete_stage(conn, s.id)
    assert [x.name for x in db.list_stages(conn, p.id, include_done=False)] == ["Reconciliação"]


# --- Invariante tarefa x etapa ----------------------------------------------


def test_set_task_stage_fills_the_project(conn):
    p = db.add_project(conn, "Janela", "fechar comissões")
    s = db.add_stage(conn, p.id, "Ingestão")
    t = db.add_task(conn, "Baixar arquivo")
    assert t.project_id is None
    vinculada = db.set_task_stage(conn, t.id, s.id)
    assert (vinculada.stage_id, vinculada.project_id) == (s.id, p.id)


def test_add_task_with_stage_derives_the_project(conn):
    p = db.add_project(conn, "Janela", "fechar comissões")
    s = db.add_stage(conn, p.id, "Ingestão")
    t = db.add_task(conn, "Baixar arquivo", stage_id=s.id)
    assert (t.stage_id, t.project_id) == (s.id, p.id)


def test_moving_task_to_another_project_drops_the_stage(conn):
    p = db.add_project(conn, "Janela", "fechar comissões")
    outro = db.add_project(conn, "Outro", "meta")
    s = db.add_stage(conn, p.id, "Ingestão")
    t = db.add_task(conn, "Baixar arquivo", stage_id=s.id)
    movida = db.set_task_project(conn, t.id, outro.id)
    assert (movida.project_id, movida.stage_id) == (outro.id, None)


def test_reassigning_to_the_same_project_keeps_the_stage(conn):
    p = db.add_project(conn, "Janela", "fechar comissões")
    s = db.add_stage(conn, p.id, "Ingestão")
    t = db.add_task(conn, "Baixar arquivo", stage_id=s.id)
    assert db.set_task_project(conn, t.id, p.id).stage_id == s.id


def test_clearing_the_stage_keeps_the_project(conn):
    p = db.add_project(conn, "Janela", "fechar comissões")
    s = db.add_stage(conn, p.id, "Ingestão")
    t = db.add_task(conn, "Baixar arquivo", stage_id=s.id)
    solta = db.set_task_stage(conn, t.id, None)
    assert (solta.stage_id, solta.project_id) == (None, p.id)


# --- Progresso --------------------------------------------------------------


def test_project_progress_counts(conn):
    p = db.add_project(conn, "Janela", "fechar comissões")
    a = db.add_task(conn, "uma", project_id=p.id)
    db.add_task(conn, "outra", project_id=p.id)
    db.complete_task(conn, a.id)
    assert db.project_progress(conn, p.id) == {"total": 2, "done": 1}


def test_project_progress_without_tasks(conn):
    p = db.add_project(conn, "Janela", "fechar comissões")
    assert db.project_progress(conn, p.id) == {"total": 0, "done": 0}


def test_stage_progress_counts(conn):
    p = db.add_project(conn, "Janela", "fechar comissões")
    s = db.add_stage(conn, p.id, "Ingestão")
    a = db.add_task(conn, "uma", stage_id=s.id)
    db.add_task(conn, "outra", stage_id=s.id)
    db.add_task(conn, "fora da etapa", project_id=p.id)
    db.complete_task(conn, a.id)
    assert db.stage_progress(conn, s.id) == {"total": 2, "done": 1}
    assert db.project_progress(conn, p.id) == {"total": 3, "done": 1}


def test_checkpoint_with_stage(conn):
    p = db.add_project(conn, "Janela", "fechar comissões")
    outro = db.add_project(conn, "Outro", "meta")
    s = db.add_stage(conn, p.id, "Ingestão")
    cp = db.add_checkpoint(conn, p.id, "relato", "avaliação", stage_id=s.id)
    assert cp.stage_id == s.id
    with pytest.raises(ValueError, match="não pertence"):
        db.add_checkpoint(conn, outro.id, "relato", "avaliação", stage_id=s.id)


# --- Rotinas ----------------------------------------------------------------


def test_add_and_find_routine(conn):
    r = db.add_routine(conn, "Janela de Comissões", "fechar no SLA", "monthly", 1, sla_days=5)
    assert (r.cadence, r.anchor, r.sla_days, r.status) == ("monthly", 1, 5, "active")
    assert db.find_routine(conn, "janela de comissões").id == r.id
    assert db.find_routine(conn, str(r.id)).id == r.id
    with pytest.raises(LookupError):
        db.find_routine(conn, "inexistente")


def test_add_routine_validates_cadence_and_anchor(conn):
    with pytest.raises(ValueError, match="Cadência inválida"):
        db.add_routine(conn, "X", "meta", "diaria", 1)
    with pytest.raises(ValueError, match="Dia de abertura inválido"):
        db.add_routine(conn, "Y", "meta", "monthly", 40)
    with pytest.raises(ValueError, match="SLA inválido"):
        db.add_routine(conn, "Z", "meta", "monthly", 1, sla_days=0)


def test_archive_routine_leaves_the_active_list(conn):
    r = db.add_routine(conn, "Janela", "meta", "monthly", 1)
    db.archive_routine(conn, r.id)
    assert db.list_routines(conn) == []
    assert len(db.list_routines(conn, include_archived=True)) == 1


def test_routine_steps_autonumber_and_replace(conn):
    r = db.add_routine(conn, "Janela", "meta", "monthly", 1)
    db.add_routine_step(conn, r.id, "Ingestão")
    db.add_routine_step(conn, r.id, "Publicação", offset_days=2)
    assert [(s.name, s.position) for s in db.list_routine_steps(conn, r.id)] == [
        ("Ingestão", 1),
        ("Publicação", 2),
    ]

    novos = db.replace_routine_steps(
        conn,
        r.id,
        [
            {"name": "Extrair", "offset_days": 0, "done_criteria": "arquivo na landing"},
            {"name": "Reconciliar", "offset_days": 1},
        ],
    )
    assert [(s.name, s.position, s.offset_days) for s in novos] == [
        ("Extrair", 1, 0),
        ("Reconciliar", 2, 1),
    ]
    assert novos[0].done_criteria == "arquivo na landing"
    assert novos[1].done_criteria is None


def test_routine_run_is_hidden_from_the_project_list(conn):
    db.add_project(conn, "Migração Glue", "meta")
    r = db.add_routine(conn, "Janela", "meta", "monthly", 1)
    db.add_routine_run(conn, r.id, "2026-08", "Janela — 2026-08", "meta", "2026-08-05")

    assert [p.name for p in db.list_projects(conn)] == ["Migração Glue"]
    assert len(db.list_projects(conn, kind=None)) == 2
    assert [p.name for p in db.list_projects(conn, kind="routine_run")] == ["Janela — 2026-08"]


def test_routine_run_fields_and_lookup(conn):
    r = db.add_routine(conn, "Janela", "meta", "monthly", 1)
    ciclo = db.add_routine_run(conn, r.id, "2026-08", "Janela — 2026-08", "meta", "2026-08-05")
    assert (ciclo.kind, ciclo.routine_id, ciclo.period) == ("routine_run", r.id, "2026-08")
    assert ciclo.deadline == "2026-08-05"
    assert db.find_routine_run(conn, r.id, "2026-08").id == ciclo.id
    assert db.find_routine_run(conn, r.id, "2026-09") is None
    assert [p.period for p in db.list_routine_runs(conn, r.id)] == ["2026-08"]


def test_duplicate_routine_run_violates_the_unique_index(conn):
    """O índice parcial (routine_id, period) é o que garante idempotência."""
    import sqlite3

    r = db.add_routine(conn, "Janela", "meta", "monthly", 1)
    db.add_routine_run(conn, r.id, "2026-08", "Janela — 2026-08", "meta")
    with pytest.raises(sqlite3.IntegrityError):
        db.add_routine_run(conn, r.id, "2026-08", "Janela — 2026-08 (bis)", "meta")


# --- Fechamento de projetos e ciclos ----------------------------------------


def test_complete_project_records_done_at(conn):
    p = db.add_project(conn, "Janela", "meta")
    feito = db.complete_project(conn, p.id)
    assert feito.status == "done"
    assert feito.done_at is not None
    assert feito.done_at[:10] == db.today()


def test_complete_project_with_explicit_date(conn):
    """Fechamento retroativo: conserta à mão um ciclo fechado fora do app."""
    p = db.add_project(conn, "Janela", "meta")
    feito = db.complete_project(conn, p.id, closed_on="2026-07-03")
    assert feito.done_at.startswith("2026-07-03")
    with pytest.raises(ValueError, match="data de fechamento"):
        db.complete_project(conn, p.id, closed_on="julho")


def test_reopen_project_clears_done_at(conn):
    p = db.add_project(conn, "Janela", "meta")
    db.complete_project(conn, p.id)
    reaberto = db.reopen_project(conn, p.id)
    assert reaberto.status == "active"
    assert reaberto.done_at is None
    assert db.list_projects(conn) == [reaberto]


def test_old_closed_project_keeps_done_at_null(conn):
    """Ciclo fechado antes da migração não ganha data inventada."""
    p = db.add_project(conn, "Antigo", "meta")
    conn.execute("UPDATE projects SET status = 'done' WHERE id = ?", (p.id,))
    conn.commit()
    assert db.get_project(conn, p.id).done_at is None


def test_sla_days_migration_runs_exactly_once(tmp_path):
    """sla_days era deslocamento e virou duração: +1, mas só na primeira vez.

    Este é o motivo de existir `_migrate_data` separado do `_MIGRATIONS`: aquele
    é keyed por coluna ausente e rodaria a transformação a cada connect().
    """
    import sqlite3

    path = tmp_path / "antigo.db"
    old = sqlite3.connect(path)
    old.executescript(
        """
        CREATE TABLE routines (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
            goal TEXT NOT NULL, cadence TEXT NOT NULL, anchor INTEGER NOT NULL,
            sla_days INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL
        );
        INSERT INTO routines (name, goal, cadence, anchor, sla_days, created_at)
            VALUES ('Janela', 'meta', 'monthly', 1, 4, '2026-01-01');
        """
    )
    old.commit()
    old.close()

    conn = db.connect(path)
    assert db.get_routine(conn, 1).sla_days == 5  # 4 de deslocamento = 5 de duração
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION

    db.connect(path)
    db.connect(path)
    assert db.get_routine(conn, 1).sla_days == 5  # não incrementa de novo


def test_new_database_is_marked_with_the_schema_version(conn):
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION


def test_add_routine_rejects_zero_sla(conn):
    with pytest.raises(ValueError, match="no mínimo 1 dia"):
        db.add_routine(conn, "X", "meta", "monthly", 1, sla_days=0)
