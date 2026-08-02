"""Testes da API web. O LLM é sempre mockado (convenção do projeto)."""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from work_assistant import config, db, llm, services
from work_assistant.web.api import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    return TestClient(app)


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    return db.connect()


def test_health(client, monkeypatch):
    monkeypatch.setattr(services, "llm_online", lambda: True)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["online"] is True
    assert body["model"] == config.LLM_MODEL


def test_index_serves_html(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "wa" in resp.text


def test_state_aggregates_tasks_and_projects(client, conn):
    db.add_task(conn, "Tarefa de hoje", priority=1)
    db.add_project(conn, "API v2", "Publicar API v2")
    resp = client.get("/api/state")
    body = resp.json()
    assert body["today"] == db.today()
    assert [t["title"] for t in body["tasks"]] == ["Tarefa de hoje"]
    assert body["projects"][0]["tag"] == "sem checkpoint"


def test_state_for_past_day(client, conn):
    db.add_task(conn, "antiga", day="2026-01-05")
    resp = client.get("/api/state", params={"day": "2026-01-05"})
    assert [t["title"] for t in resp.json()["tasks"]] == ["antiga"]


def test_add_task_and_toggle(client):
    created = client.post("/api/tasks", json={"title": "Nova tarefa"}).json()
    assert created["done"] is False

    done = client.post(f"/api/tasks/{created['id']}/toggle").json()
    assert done["done"] is True

    reopened = client.post(f"/api/tasks/{created['id']}/toggle").json()
    assert reopened["done"] is False


def test_add_task_empty_title_rejected(client):
    assert client.post("/api/tasks", json={"title": "   "}).status_code == 422


def test_add_task_with_due_tags_effort(client):
    created = client.post(
        "/api/tasks",
        json={"title": "Nova", "due_date": "2030-01-05", "tags": ["Bug", "dados"], "effort": "m"},
    ).json()
    assert created["due"] == "2030-01-05"
    assert created["tags"] == ["bug", "dados"]
    assert created["effort"] == "M"
    assert created["source"] == "manual"


def test_add_task_invalid_due_422(client):
    resp = client.post("/api/tasks", json={"title": "x", "due_date": "amanhã"})
    assert resp.status_code == 422
    assert "YYYY-MM-DD" in resp.json()["detail"]


def test_add_task_with_project(client, conn):
    project = db.add_project(conn, "API v2", "Publicar API v2")
    created = client.post(
        "/api/tasks", json={"title": "Endpoint de auth", "project_id": project.id}
    ).json()
    assert created["project_id"] == project.id
    assert created["project_name"] == "API v2"


def test_add_task_invalid_project_422(client):
    resp = client.post("/api/tasks", json={"title": "x", "project_id": 999})
    assert resp.status_code == 422


def test_set_task_project_endpoint(client, conn):
    project = db.add_project(conn, "API v2", "Publicar API v2")
    task = db.add_task(conn, "sem projeto")

    resp = client.post(f"/api/tasks/{task.id}/project", json={"project_id": project.id})
    body = resp.json()
    assert body["project_id"] == project.id
    assert body["project_name"] == "API v2"

    cleared = client.post(f"/api/tasks/{task.id}/project", json={"project_id": None}).json()
    assert cleared["project_id"] is None


def test_set_task_project_missing_task_404(client):
    resp = client.post("/api/tasks/999/project", json={"project_id": None})
    assert resp.status_code == 404


def test_set_task_project_invalid_project_404(client, conn):
    task = db.add_task(conn, "sem projeto")
    resp = client.post(f"/api/tasks/{task.id}/project", json={"project_id": 999})
    assert resp.status_code == 404


def test_edit_task_sets_all_fields(client, conn):
    project = db.add_project(conn, "API v2", "Publicar API v2")
    task = db.add_task(conn, "Corrigir job")
    body = {
        "project_id": project.id,
        "tags": ["Bug", "dados"],
        "due_date": "2030-01-05",
        "effort": "g",
    }
    edited = client.post(f"/api/tasks/{task.id}", json=body).json()
    assert edited["project_id"] == project.id
    assert edited["project_name"] == "API v2"
    assert edited["tags"] == ["bug", "dados"]
    assert edited["due"] == "2030-01-05"
    assert edited["effort"] == "G"


def test_edit_task_clears_fields(client, conn):
    project = db.add_project(conn, "API v2", "Publicar API v2")
    task = db.add_task(
        conn, "x", project_id=project.id, tags="bug", due_date="2030-01-05", effort="M"
    )
    edited = client.post(f"/api/tasks/{task.id}", json={}).json()
    assert edited["project_id"] is None
    assert edited["tags"] == []
    assert edited["due"] is None
    assert edited["effort"] is None


def test_edit_task_invalid_due_422(client, conn):
    task = db.add_task(conn, "x")
    resp = client.post(f"/api/tasks/{task.id}", json={"due_date": "amanhã"})
    assert resp.status_code == 422


def test_edit_task_invalid_project_404(client, conn):
    task = db.add_task(conn, "x")
    resp = client.post(f"/api/tasks/{task.id}", json={"project_id": 999})
    assert resp.status_code == 404


def test_edit_task_missing_task_404(client):
    assert client.post("/api/tasks/999", json={}).status_code == 404


def test_project_timeline_includes_status(client, conn):
    project = db.add_project(conn, "API v2", "Publicar API v2")
    db.add_checkpoint(conn, project.id, "relato", "aval", status="em risco", summary="Resumo.")
    out = client.get("/api/state").json()["projects"][0]
    assert out["timeline"][0]["status"] == "em risco"


def test_project_out_includes_task_counts(client, conn):
    project = client.post("/api/projects", json={"name": "API v2", "goal": "meta"}).json()
    done_task = db.add_task(conn, "feita", project_id=project["id"])
    db.add_task(conn, "pendente", project_id=project["id"])
    db.complete_task(conn, done_task.id)
    state = client.get("/api/state").json()
    tasks = state["projects"][0]["tasks"]
    assert tasks["total"] == 2
    assert tasks["done"] == 1


def test_toggle_missing_task_404(client):
    assert client.post("/api/tasks/999/toggle").status_code == 404


def test_project_lifecycle_and_tag(client, conn):
    created = client.post(
        "/api/projects", json={"name": "API v2", "goal": "Publicar API v2"}
    ).json()
    assert created["tag"] == "sem checkpoint"

    db.add_checkpoint(
        conn, created["id"], "relato", "aval", status="em risco", summary="Em risco — infra."
    )
    project = client.get("/api/state").json()["projects"][0]
    assert project["tag"] == "em risco"
    assert project["timeline"][0]["summary"] == "Em risco — infra."

    finished = client.post(f"/api/projects/{created['id']}/done").json()
    assert finished["tag"] == "concluído"
    assert finished["active"] is False


def test_plan_suggests_and_saves_with_dedupe(client, conn, monkeypatch):
    db.add_task(conn, "Já existe")
    suggested = {
        "tasks": [
            {"title": "Já existe", "priority": 1},
            {"title": "Nova do modelo", "priority": 2},
        ]
    }
    monkeypatch.setattr(llm, "structured", lambda *a, **k: suggested)

    resp = client.post("/api/plan", json={"relato": "meu dia"})
    assert [t["title"] for t in resp.json()["tasks"]] == ["Já existe", "Nova do modelo"]

    saved = client.post("/api/plan/save", json=suggested).json()
    titles = [t["title"] for t in saved["tasks"]]
    assert titles.count("Já existe") == 1
    assert "Nova do modelo" in titles


def test_add_project_with_deadline(client):
    created = client.post(
        "/api/projects", json={"name": "X", "goal": "meta", "deadline": "2030-05-01"}
    ).json()
    assert created["deadline"] == "2030-05-01"


def test_plan_save_records_source_and_fields(client, conn):
    suggested = {
        "tasks": [
            {"title": "Do modelo", "priority": 1, "due_date": db.today(), "tags": ["dados"], "effort": "M"}
        ]
    }
    client.post("/api/plan/save", json=suggested)
    task = db.list_tasks(conn)[0]
    assert task.source == "plan"
    assert task.tags == "dados"
    assert task.effort == "M"
    assert task.due_date == db.today()


def test_checkpoint_saves_status_and_summary(client, conn, monkeypatch):
    project = db.add_project(conn, "API v2", "Publicar API v2")
    monkeypatch.setattr(
        llm,
        "structured",
        lambda *a, **k: {
            "situacao": "Avançando bem.",
            "riscos": "Testes adiados.",
            "proximo_passo": ["Fechar auth", "Escrever testes"],
            "vereditos": [],
            "status": "no rumo",
            "resumo": "No rumo — falta auth.",
        },
    )
    resp = client.post(
        "/api/checkpoint", json={"project_id": project.id, "progress": "auth quase pronta"}
    )
    body = resp.json()
    assert [b["title"] for b in body["blocks"]] == ["Situação", "Riscos e desvios", "Próximo passo"]
    assert "1. Fechar auth" in body["blocks"][2]["body"]

    cp = db.list_checkpoints(conn, project.id)[-1]
    assert cp.status == "no rumo"
    assert cp.summary == "No rumo — falta auth."
    assert "**Situação**" in cp.assessment


def test_checkpoint_missing_project_404(client):
    resp = client.post("/api/checkpoint", json={"project_id": 999, "progress": "x"})
    assert resp.status_code == 404


def test_chat_uses_history(client, monkeypatch):
    captured = {}

    def fake_complete(system, user, history=None, quality=False):
        captured["history"] = history
        return "Resposta do modelo"

    monkeypatch.setattr(llm, "complete", fake_complete)
    resp = client.post(
        "/api/chat",
        json={"message": "e agora?", "history": [{"role": "user", "content": "oi"}]},
    )
    assert resp.json()["reply"] == "Resposta do modelo"
    assert captured["history"] == [{"role": "user", "content": "oi"}]


def test_review_metrics_endpoint(client, conn):
    done = db.add_task(conn, "feita", due_date=db.today(), tags="bug", effort="P", source="plan")
    db.complete_task(conn, done.id)
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    db.add_task(conn, "atrasada", due_date=yesterday, tags="dados")

    body = client.get("/api/review", params={"days": 7}).json()
    assert body["total"] == 2
    assert body["done"] == 1
    assert [t["title"] for t in body["overdue"]] == ["atrasada"]
    assert body["on_time_rate"] == 1.0
    assert body["unplanned_rate"] == 0.5
    assert body["carryover_rate"] == 0.0
    assert body["by_tag"]["dados"]["overdue"] == 1
    assert body["by_effort"]["P"]["done"] == 1
    assert len(body["per_day"]) == 7
    assert body["per_day"][-1] == {
        "day": db.today(), "done": 1, "run": 0, "change": 0, "loose": 1
    }


def test_review_assessment(client, conn, monkeypatch):
    task = db.add_task(conn, "feita")
    db.complete_task(conn, task.id)
    monkeypatch.setattr(llm, "complete", lambda *a, **k: "**Avaliação** do período.")
    body = client.post("/api/review", json={"days": 7}).json()
    assert body["assessment"] == "**Avaliação** do período."
    assert body["metrics"]["done"] == 1


def test_review_without_tasks_409(client):
    assert client.post("/api/review", json={"days": 7}).status_code == 409


def test_review_metrics_by_project(client, conn):
    project = db.add_project(conn, "API v2", "Publicar API v2")
    done = db.add_task(conn, "feita", project_id=project.id)
    db.complete_task(conn, done.id)
    db.add_task(conn, "sem projeto")

    body = client.get("/api/review", params={"days": 7}).json()
    entry = body["by_project"][str(project.id)]
    assert entry["name"] == "API v2"
    assert entry["total"] == 1
    assert entry["done"] == 1


def test_llm_offline_returns_503(client, conn, monkeypatch):
    import openai

    def boom(*a, **k):
        raise openai.APIConnectionError(request=None)

    monkeypatch.setattr(llm, "structured", boom)
    resp = client.post("/api/plan", json={"relato": "meu dia"})
    assert resp.status_code == 503
    assert "offline" in resp.json()["detail"]


# --- Etapas e ciclos de rotina ----------------------------------------------


def _rotina(conn):
    """Rotina mensal que abre no dia 1, cadastrada no mês anterior.

    O created_at é recuado de propósito: uma rotina criada depois da abertura do
    período não materializa o ciclo corrente (é o que `wa routine run` resolve).
    """
    routine = db.add_routine(conn, "Janela de Comissões", "fechar no SLA", "monthly", 1, sla_days=4)
    db.replace_routine_steps(
        conn,
        routine.id,
        [{"name": "Extrair base", "offset_days": 0}, {"name": "Reconciliar", "offset_days": 1}],
    )
    inicio_do_mes = db.today()[:8] + "01"
    conn.execute("UPDATE routines SET created_at = ? WHERE id = ?", (inicio_do_mes, routine.id))
    conn.commit()
    return db.get_routine(conn, routine.id)


def test_state_materializes_and_separates_routine_runs(client, conn):
    db.add_project(conn, "Migração Glue", "meta")
    _rotina(conn)

    state = client.get("/api/state").json()
    assert [p["name"] for p in state["projects"]] == ["Migração Glue"]
    assert len(state["routine_runs"]) == 1
    assert state["routine_runs"][0]["name"].startswith("Janela de Comissões — ")


def test_state_is_idempotent_across_requests(client, conn):
    _rotina(conn)
    client.get("/api/state")
    client.get("/api/state")
    assert len(db.list_projects(conn, kind="routine_run")) == 1


def test_routine_run_task_keeps_its_project_name(client, conn):
    """Sem kind=None no _project_map a tarefa do ciclo apareceria sem projeto."""
    _rotina(conn)
    client.get("/api/state")  # materializa
    ciclo = db.list_projects(conn, kind="routine_run")[0]
    stage = db.list_stages(conn, ciclo.id)[0]
    task = db.add_task(conn, "Baixar arquivo", stage_id=stage.id)

    state = client.get("/api/state").json()
    linha = next(t for t in state["tasks"] if t["id"] == task.id)
    assert linha["project_id"] == ciclo.id
    assert linha["project_name"] == ciclo.name


def test_editing_a_routine_run_task_keeps_the_link(client, conn):
    """Regressão do popover: salvar sem mexer no projeto não pode desvincular."""
    _rotina(conn)
    client.get("/api/state")
    ciclo = db.list_projects(conn, kind="routine_run")[0]
    task = db.add_task(conn, "Baixar arquivo", project_id=ciclo.id)

    r = client.post(f"/api/tasks/{task.id}", json={"project_id": ciclo.id, "tags": ["dados"]})
    assert r.status_code == 200
    assert db.get_task(conn, task.id).project_id == ciclo.id


def test_project_out_uses_canonical_progress(client, conn):
    p = db.add_project(conn, "Janela", "meta")
    a = db.add_task(conn, "uma", project_id=p.id)
    db.add_task(conn, "outra", project_id=p.id)
    db.complete_task(conn, a.id)
    state = client.get("/api/state").json()
    assert state["projects"][0]["tasks"] == {"total": 2, "done": 1}


# --- Etapas e campos derivados no /api/state --------------------------------


def _projeto_com_etapas(conn, today="2026-08-02"):
    p = db.add_project(conn, "Migração Glue", "meta", deadline="2026-09-30")
    a = db.add_stage(conn, p.id, "Extrair", deadline="2026-08-01", done_criteria="arquivo na landing")
    b = db.add_stage(conn, p.id, "Reconciliar", deadline="2026-08-01", done_criteria="diferença < 0,01%")
    db.add_stage(conn, p.id, "Publicar", deadline="2026-08-20")
    db.complete_stage(conn, a.id)
    return p, b


def test_state_exposes_stages_with_derived_fields(client, conn):
    p, atrasada = _projeto_com_etapas(conn)
    db.add_task(conn, "uma", stage_id=atrasada.id)

    proj = client.get("/api/state").json()["projects"][0]
    assert proj["kind"] == "project"
    assert proj["current_stage_id"] == atrasada.id
    assert proj["stages_progress"] == {"total": 3, "done": 1, "overdue": 1}

    etapas = {s["name"]: s for s in proj["stages"]}
    assert etapas["Extrair"]["done"] is True
    assert etapas["Extrair"]["overdue"] is False  # feita não conta como atrasada
    assert etapas["Reconciliar"]["is_current"] is True
    assert etapas["Reconciliar"]["overdue"] is True
    assert etapas["Reconciliar"]["days_overdue"] >= 1
    assert etapas["Reconciliar"]["done_criteria"] == "diferença < 0,01%"
    assert etapas["Reconciliar"]["tasks"] == {"total": 1, "done": 0}
    assert etapas["Publicar"]["is_current"] is False


def test_state_task_carries_stage(client, conn):
    p, etapa = _projeto_com_etapas(conn)
    t = db.add_task(conn, "Investigar divergência", stage_id=etapa.id)
    linha = next(x for x in client.get("/api/state").json()["tasks"] if x["id"] == t.id)
    assert linha["stage_id"] == etapa.id
    assert linha["stage_name"] == "Reconciliar"
    assert linha["project_kind"] == "project"


def test_state_stage_carries_last_verdict(client, conn):
    p, etapa = _projeto_com_etapas(conn)
    cp = db.add_checkpoint(conn, p.id, "relato", "avaliação")
    db.add_checkpoint_verdicts(
        conn, cp.id, [{"stage_id": etapa.id, "verdict": "nao_atende", "rationale": "sem batimento"}]
    )
    proj = client.get("/api/state").json()["projects"][0]
    etapas = {s["name"]: s for s in proj["stages"]}
    assert etapas["Reconciliar"]["verdict"]["verdict"] == "nao_atende"
    assert etapas["Reconciliar"]["verdict"]["label"] == "não atende"
    assert etapas["Reconciliar"]["verdict"]["rationale"] == "sem batimento"
    assert etapas["Extrair"]["verdict"] is None


def test_routine_run_carries_routine_vocabulary(client, conn):
    _rotina(conn)
    client.get("/api/state")  # materializa
    ciclo = client.get("/api/state").json()["routine_runs"][0]

    assert ciclo["kind"] == "routine_run"
    assert ciclo["routine_name"] == "Janela de Comissões"
    assert ciclo["period_label"] == f"ciclo {ciclo['period']}"
    assert ciclo["cadence"] == "mensal"
    assert ciclo["window_label"] == "01–05 de cada mês"
    assert ciclo["open"] is True
    assert ciclo["closed_on_time"] is None
    assert isinstance(ciclo["sla_left_days"], int)
    assert [s["name"] for s in ciclo["stages"]] == ["Extrair base", "Reconciliar"]


def test_closed_cycle_reports_sla(client, conn):
    _rotina(conn)
    client.get("/api/state")
    ciclo_db = db.list_projects(conn, kind="routine_run")[0]
    db.complete_project(conn, ciclo_db.id, closed_on=ciclo_db.deadline)

    ciclo = client.get("/api/state").json()["routine_runs"][0]
    assert ciclo["open"] is False
    assert ciclo["closed_on_time"] is True
    assert ciclo["tag"] == "concluído"


def test_cycle_closed_before_migration_has_unknown_sla(client, conn):
    """done_at NULL é um terceiro estado — não vira 'fechado no prazo' por omissão."""
    _rotina(conn)
    client.get("/api/state")
    ciclo_db = db.list_projects(conn, kind="routine_run")[0]
    conn.execute("UPDATE projects SET status = 'done' WHERE id = ?", (ciclo_db.id,))
    conn.commit()

    ciclo = client.get("/api/state").json()["routine_runs"][0]
    assert ciclo["open"] is False
    assert ciclo["closed_on_time"] is None


def test_state_does_not_do_n_plus_one_on_stages(client, conn, monkeypatch):
    """Etapas e progresso vêm em agregados; a tela não pode custar uma query por etapa."""
    for n in range(4):
        p = db.add_project(conn, f"Projeto {n}", "meta")
        for m in range(4):
            db.add_stage(conn, p.id, f"Etapa {m}")

    contador = {"n": 0}
    original = db.connect

    def contando(*args, **kwargs):
        c = original(*args, **kwargs)
        c.set_trace_callback(lambda _sql: contador.__setitem__("n", contador["n"] + 1))
        return c

    monkeypatch.setattr(db, "connect", contando)
    client.get("/api/state")

    # 4 projetos x 4 etapas = 16 etapas; uma query por etapa passaria de 60.
    assert contador["n"] < 60, f"{contador['n']} statements — o N+1 voltou"


def test_state_exposes_ritual_counts_and_routines(client, conn):
    _rotina(conn)
    state = client.get("/api/state").json()

    assert state["counts"]["rotinas"] == 1
    assert isinstance(state["ritual"], list)
    assert len(state["ritual"]) <= 3

    rotina = state["routines"][0]
    assert rotina["name"] == "Janela de Comissões"
    assert rotina["cadence"] == "mensal"
    assert rotina["window_label"] == "01–05 de cada mês"
    assert [s["name"] for s in rotina["steps"]] == ["Extrair base", "Reconciliar"]
    assert rotina["sla_history"] == {"closed": 0, "on_time": 0, "rate": None}


def test_routine_sla_history_ignores_cycles_without_done_at(client, conn):
    _rotina(conn)
    client.get("/api/state")
    ciclo = db.list_projects(conn, kind="routine_run")[0]
    conn.execute("UPDATE projects SET status = 'done' WHERE id = ?", (ciclo.id,))
    conn.commit()

    rotina = client.get("/api/state").json()["routines"][0]
    assert rotina["sla_history"]["closed"] == 0  # fechado sem data fica fora do cálculo
    assert rotina["sla_history"]["rate"] is None


def test_edit_task_sets_stage(client, conn):
    p, etapa = _projeto_com_etapas(conn)
    task = db.add_task(conn, "Investigar divergência")
    edited = client.post(
        f"/api/tasks/{task.id}", json={"project_id": p.id, "stage_id": etapa.id}
    ).json()
    assert edited["stage_id"] == etapa.id
    assert edited["stage_name"] == "Reconciliar"
    assert edited["project_id"] == p.id


def test_edit_task_stage_from_another_project_422(client, conn):
    """Sem a guarda, a tarefa migraria em silêncio para o projeto da etapa."""
    p, etapa = _projeto_com_etapas(conn)
    outro = db.add_project(conn, "Outro", "meta")
    task = db.add_task(conn, "x", project_id=outro.id)

    resp = client.post(f"/api/tasks/{task.id}", json={"project_id": outro.id, "stage_id": etapa.id})
    assert resp.status_code == 422
    assert "não pertence" in resp.json()["detail"]
    assert db.get_task(conn, task.id).project_id == outro.id


def test_edit_task_changing_project_drops_the_stage(client, conn):
    p, etapa = _projeto_com_etapas(conn)
    outro = db.add_project(conn, "Outro", "meta")
    task = db.add_task(conn, "x", stage_id=etapa.id)

    edited = client.post(f"/api/tasks/{task.id}", json={"project_id": outro.id}).json()
    assert edited["project_id"] == outro.id
    assert edited["stage_id"] is None


def test_edit_task_keeps_stage_when_resent(client, conn):
    """Regressão: salvar o popover sem mexer no destino não pode apagar a etapa."""
    p, etapa = _projeto_com_etapas(conn)
    task = db.add_task(conn, "x", stage_id=etapa.id)

    edited = client.post(
        f"/api/tasks/{task.id}",
        json={"project_id": p.id, "stage_id": etapa.id, "tags": ["dados"]},
    ).json()
    assert edited["stage_id"] == etapa.id
    assert db.get_task(conn, task.id).stage_id == etapa.id
