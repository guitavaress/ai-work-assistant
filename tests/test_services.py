"""Materialização de ciclos de rotina — não toca no modelo."""

import pytest

from work_assistant import db, services


@pytest.fixture
def conn(tmp_path):
    return db.connect(tmp_path / "test.db")


def _janela(conn, created_at="2026-08-01", anchor=1, sla_days=4, cadence="monthly"):
    """Rotina mensal com 3 passos, com created_at forçado para testar backfill."""
    routine = db.add_routine(
        conn, "Janela de Comissões", "fechar no SLA", cadence, anchor, sla_days=sla_days
    )
    db.replace_routine_steps(
        conn,
        routine.id,
        [
            {"name": "Extrair base", "offset_days": 0, "done_criteria": "arquivo na landing"},
            {"name": "Reconciliar", "offset_days": 1, "done_criteria": "diferença < 0,01%"},
            {"name": "Publicar", "offset_days": 2},
        ],
    )
    conn.execute("UPDATE routines SET created_at = ? WHERE id = ?", (created_at, routine.id))
    conn.commit()
    return db.get_routine(conn, routine.id)


def test_ensure_routines_without_routines_is_a_noop(conn):
    assert services.ensure_routines(conn, today="2026-08-10") == []


def test_materializes_the_cycle_with_stages(conn):
    routine = _janela(conn)
    created = services.ensure_routines(conn, today="2026-08-03")

    assert len(created) == 1
    ciclo = created[0]
    assert ciclo.name == "Janela de Comissões — 2026-08"
    assert ciclo.kind == "routine_run"
    assert ciclo.period == "2026-08"
    assert ciclo.goal == routine.goal  # cópia do objetivo da rotina
    assert ciclo.deadline == "2026-08-05"  # abertura 01/08 + sla_days 4

    stages = db.list_stages(conn, ciclo.id)
    assert [(s.name, s.position, s.deadline) for s in stages] == [
        ("Extrair base", 1, "2026-08-01"),
        ("Reconciliar", 2, "2026-08-02"),
        ("Publicar", 3, "2026-08-03"),
    ]
    assert stages[1].done_criteria == "diferença < 0,01%"
    assert stages[2].done_criteria is None


def test_ensure_routines_is_idempotent(conn):
    _janela(conn)
    assert len(services.ensure_routines(conn, today="2026-08-03")) == 1
    assert services.ensure_routines(conn, today="2026-08-03") == []
    assert len(db.list_projects(conn, kind="routine_run")) == 1


def test_backfills_missed_cycles(conn):
    """Ficar semanas sem abrir o app não pode perder o registro dos ciclos."""
    _janela(conn, created_at="2026-08-01")
    created = services.ensure_routines(conn, today="2026-10-15")
    assert [p.period for p in created] == ["2026-08", "2026-09", "2026-10"]


def test_does_not_materialize_before_the_routine_existed(conn):
    """Rotina cadastrada em outubro não inventa ciclos de agosto e setembro."""
    _janela(conn, created_at="2026-10-05")
    created = services.ensure_routines(conn, today="2026-10-20")
    assert created == []  # a abertura de outubro (dia 1) é anterior ao cadastro

    created = services.ensure_routines(conn, today="2026-11-10")
    assert [p.period for p in created] == ["2026-11"]


def test_lookback_caps_the_backfill(conn):
    """Rotina antiga demais não despeja um ano de ciclos no primeiro comando."""
    _janela(conn, created_at="2024-01-01")
    created = services.ensure_routines(conn, today="2026-10-15")
    assert len(created) <= services.ROUTINE_LOOKBACK_DAYS // 28
    assert [p.period for p in created] == ["2026-08", "2026-09", "2026-10"]


def test_cycle_not_open_yet_is_not_materialized(conn):
    """Rotina que abre dia 15: no dia 3 o ciclo do mês ainda não existe."""
    _janela(conn, created_at="2026-08-01", anchor=15)
    assert services.ensure_routines(conn, today="2026-08-03") == []
    assert len(services.ensure_routines(conn, today="2026-08-15")) == 1


def test_cycle_is_hidden_from_the_project_list(conn):
    db.add_project(conn, "Migração Glue", "meta")
    _janela(conn)
    services.ensure_routines(conn, today="2026-08-03")
    assert [p.name for p in db.list_projects(conn)] == ["Migração Glue"]
    assert len(db.list_projects(conn, kind=None)) == 2


def test_name_collision_with_a_manual_project(conn):
    """Um projeto criado na mão com o nome do ciclo não pode travar a materialização."""
    routine = _janela(conn)
    db.add_project(conn, f"{routine.name} — 2026-08", "projeto homônimo criado na mão")
    created = services.ensure_routines(conn, today="2026-08-03")
    assert len(created) == 1
    assert created[0].name.endswith(f"(#{routine.id})")
    assert created[0].period == "2026-08"


def test_weekly_routine(conn):
    _janela(conn, created_at="2026-08-01", anchor=1, sla_days=1, cadence="weekly")
    created = services.ensure_routines(conn, today="2026-08-12")
    # segundas de agosto a partir do dia 01: 03/08 e 10/08
    assert [p.period for p in created] == ["2026-W32", "2026-W33"]
    assert created[0].deadline == "2026-08-04"


def test_routine_view(conn):
    routine = _janela(conn)
    services.ensure_routines(conn, today="2026-08-03")
    ciclo = db.list_projects(conn, kind="routine_run")[0]
    stages = db.list_stages(conn, ciclo.id)
    db.complete_stage(conn, stages[0].id)
    db.add_task(conn, "Baixar arquivo", stage_id=stages[0].id)

    view = services.routine_view(conn, routine)
    assert view["cadence"] == "mensal, dia 1 (+4d)"
    assert [s.name for s in view["steps"]] == ["Extrair base", "Reconciliar", "Publicar"]
    assert view["runs"][0]["stages"] == {"total": 3, "done": 1}
    assert view["runs"][0]["tasks"] == {"total": 1, "done": 0}


def test_close_routine_run(conn):
    _janela(conn)
    services.ensure_routines(conn, today="2026-08-03")
    ciclo = db.list_projects(conn, kind="routine_run")[0]
    assert services.close_routine_run(conn, ciclo).status == "done"


# --- Contexto e checkpoint ciente de etapas ---------------------------------


def test_stages_block_marks_overdue_and_focus(conn, monkeypatch):
    from work_assistant import context

    monkeypatch.setattr(db, "today", lambda: "2026-08-10")
    p = db.add_project(conn, "Janela", "fechar comissões")
    a = db.add_stage(conn, p.id, "Extrair base", deadline="2026-08-01",
                     done_criteria="arquivo na landing")
    b = db.add_stage(conn, p.id, "Reconciliar", deadline="2026-08-02",
                     done_criteria="diferença < 0,01%")
    db.complete_stage(conn, a.id)
    db.add_task(conn, "Investigar conta 4021", stage_id=b.id)

    bloco = context.stages_block(conn, p.id, stage_id=b.id)
    assert "1. [feita] Extrair base — prazo 2026-08-01" in bloco
    assert ">>> 2. [pendente] Reconciliar — prazo 2026-08-02 ATRASADA" in bloco
    assert "pronto quando: diferença < 0,01%" in bloco
    assert "pendentes: Investigar conta 4021" in bloco


def test_stages_block_without_stages(conn):
    from work_assistant import context

    p = db.add_project(conn, "Janela", "meta")
    assert context.stages_block(conn, p.id) == "Este projeto não tem etapas definidas."


def test_routine_runs_block(conn):
    from work_assistant import context

    assert context.routine_runs_block(conn) == "Nenhuma rotina em andamento."
    _janela(conn)
    services.ensure_routines(conn, today="2026-08-03")
    ciclo = db.list_projects(conn, kind="routine_run")[0]
    db.complete_stage(conn, db.list_stages(conn, ciclo.id)[0].id)

    bloco = context.routine_runs_block(conn)
    assert "Janela de Comissões — 2026-08" in bloco
    assert "1/3 etapas" in bloco
    assert "falta: Reconciliar, Publicar" in bloco


def test_run_checkpoint_sends_stages_and_saves_the_link(conn, monkeypatch):
    from work_assistant import llm

    capturado = {}

    def fake_structured(system, user_message, schema, **kwargs):
        capturado["user_message"] = user_message
        return {
            "situacao": "Reconciliação parada.",
            "riscos": "Critério de diferença não foi verificado.",
            "proximo_passo": ["Rodar o batimento"],
            "status": "em risco",
            "resumo": "Em risco — reconciliação sem batimento.",
        }

    monkeypatch.setattr(llm, "structured", fake_structured)
    p = db.add_project(conn, "Janela", "fechar comissões")
    etapa = db.add_stage(conn, p.id, "Reconciliar", done_criteria="diferença < 0,01%")

    result = services.run_checkpoint(conn, p, "avancei no de-para", stage=etapa)

    assert "Etapa em foco: Reconciliar" in capturado["user_message"]
    assert "pronto quando: diferença < 0,01%" in capturado["user_message"]
    assert result["status"] == "em risco"
    assert db.list_checkpoints(conn, p.id)[0].stage_id == etapa.id


def test_run_checkpoint_without_stage_still_works(conn, monkeypatch):
    from work_assistant import llm

    monkeypatch.setattr(
        llm,
        "structured",
        lambda *a, **k: {
            "situacao": "ok",
            "riscos": "nenhum",
            "proximo_passo": ["seguir"],
            "status": "no rumo",
            "resumo": "No rumo.",
        },
    )
    p = db.add_project(conn, "Janela", "fechar comissões")
    services.run_checkpoint(conn, p, "tudo certo")
    assert db.list_checkpoints(conn, p.id)[0].stage_id is None
