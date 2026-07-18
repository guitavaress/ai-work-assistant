"""Testes da API web. O LLM é sempre mockado (convenção do projeto)."""

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


def test_checkpoint_saves_status_and_summary(client, conn, monkeypatch):
    project = db.add_project(conn, "API v2", "Publicar API v2")
    monkeypatch.setattr(
        llm,
        "structured",
        lambda *a, **k: {
            "situacao": "Avançando bem.",
            "riscos": "Testes adiados.",
            "proximo_passo": ["Fechar auth", "Escrever testes"],
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


def test_standup_returns_blocks(client, conn, monkeypatch):
    db.add_task(conn, "Feita ontem", day=db.today())
    monkeypatch.setattr(
        llm,
        "structured",
        lambda *a, **k: {"ontem": "Fechei X.", "hoje": "Vou fazer Y.", "impedimentos": "Sem impedimentos"},
    )
    body = client.post("/api/standup", json={"days": 1}).json()
    assert [b["title"] for b in body["blocks"]] == ["Ontem", "Hoje", "Impedimentos"]


def test_standup_without_history_409(client):
    assert client.post("/api/standup", json={"days": 1}).status_code == 409


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


def test_llm_offline_returns_503(client, conn, monkeypatch):
    import openai

    def boom(*a, **k):
        raise openai.APIConnectionError(request=None)

    monkeypatch.setattr(llm, "structured", boom)
    resp = client.post("/api/plan", json={"relato": "meu dia"})
    assert resp.status_code == 503
    assert "offline" in resp.json()["detail"]
