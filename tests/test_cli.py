import pytest
from typer.testing import CliRunner

from work_assistant import config, llm
from work_assistant.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "assistant.db")


def test_todo_add_list_done():
    result = runner.invoke(app, ["todo", "add", "Revisar PR", "-p", "1"])
    assert result.exit_code == 0
    assert "Tarefa #1 adicionada" in result.output

    result = runner.invoke(app, ["todo", "list"])
    assert result.exit_code == 0
    assert "Revisar PR" in result.output

    result = runner.invoke(app, ["todo", "done", "1"])
    assert result.exit_code == 0
    assert "Concluída" in result.output

    result = runner.invoke(app, ["todo", "list", "--pending"])
    assert "Revisar PR" not in result.output


def test_todo_add_with_due_tags_effort():
    result = runner.invoke(
        app, ["todo", "add", "Corrigir job", "-D", "2030-01-05", "-t", "bug", "-t", "dados", "-e", "m"]
    )
    assert result.exit_code == 0
    assert "2030-01-05" in result.output

    result = runner.invoke(app, ["todo", "list"])
    assert "bug" in result.output
    assert "M" in result.output


def test_todo_add_invalid_due():
    result = runner.invoke(app, ["todo", "add", "x", "--due", "05/01/2030"])
    assert result.exit_code == 1
    assert "YYYY-MM-DD" in result.output


def test_todo_due_and_tag_commands():
    runner.invoke(app, ["todo", "add", "Ajustar pipeline"])
    result = runner.invoke(app, ["todo", "due", "1", "2030-02-01"])
    assert result.exit_code == 0
    assert "2030-02-01" in result.output

    result = runner.invoke(app, ["todo", "tag", "1", "dados", "pipeline"])
    assert result.exit_code == 0
    assert "dados,pipeline" in result.output


def test_todo_done_missing_task():
    result = runner.invoke(app, ["todo", "done", "42"])
    assert result.exit_code == 1
    assert "não encontrada" in result.output


def test_todo_add_with_project():
    runner.invoke(app, ["project", "add", "API v2", "--goal", "Publicar API v2"])
    result = runner.invoke(app, ["todo", "add", "Endpoint de auth", "-P", "API v2"])
    assert result.exit_code == 0
    assert "projeto: API v2" in result.output

    result = runner.invoke(app, ["todo", "list"])
    assert "API v2" in result.output


def test_todo_add_invalid_project():
    result = runner.invoke(app, ["todo", "add", "x", "-P", "inexistente"])
    assert result.exit_code == 1
    assert "não encontrado" in result.output


def test_todo_project_command():
    runner.invoke(app, ["project", "add", "API v2", "--goal", "Publicar API v2"])
    runner.invoke(app, ["todo", "add", "Sem projeto"])
    result = runner.invoke(app, ["todo", "project", "1", "API v2"])
    assert result.exit_code == 0
    assert "API v2" in result.output


def test_todo_list_filtered_by_project():
    runner.invoke(app, ["project", "add", "API v2", "--goal", "Publicar API v2"])
    runner.invoke(app, ["project", "add", "Outro", "--goal", "meta"])
    runner.invoke(app, ["todo", "add", "Da API", "-P", "API v2"])
    runner.invoke(app, ["todo", "add", "Do outro", "-P", "Outro"])

    result = runner.invoke(app, ["todo", "list", "--project", "API v2"])
    assert "Da API" in result.output
    assert "Do outro" not in result.output


def test_project_add_and_list():
    result = runner.invoke(
        app, ["project", "add", "Faturamento", "--goal", "Migrar cobrança até a sprint 12"]
    )
    assert result.exit_code == 0
    assert "Projeto #1 criado" in result.output

    result = runner.invoke(app, ["project", "list"])
    assert "Faturamento" in result.output

    result = runner.invoke(app, ["project", "done", "Faturamento"])
    assert result.exit_code == 0

    result = runner.invoke(app, ["project", "list"])
    assert "Faturamento" not in result.output


def test_project_deadline_command():
    runner.invoke(app, ["project", "add", "Faturamento", "--goal", "Migrar cobrança"])
    result = runner.invoke(app, ["project", "deadline", "Faturamento", "2030-03-01"])
    assert result.exit_code == 0
    assert "2030-03-01" in result.output


def test_project_list_shows_task_count():
    runner.invoke(app, ["project", "add", "Faturamento", "--goal", "Migrar cobrança"])
    runner.invoke(app, ["todo", "add", "Tarefa 1", "-P", "Faturamento"])
    runner.invoke(app, ["todo", "add", "Tarefa 2", "-P", "Faturamento"])
    runner.invoke(app, ["todo", "done", "1"])

    result = runner.invoke(app, ["project", "list"])
    assert result.exit_code == 0
    assert "1/2" in result.output


def test_review_shows_metrics_and_assessment(monkeypatch):
    runner.invoke(app, ["todo", "add", "Feita", "-t", "bug", "-e", "P"])
    runner.invoke(app, ["todo", "done", "1"])
    monkeypatch.setattr(llm, "complete", lambda *a, **k: "Avaliação do período aqui.")

    result = runner.invoke(app, ["review"])
    assert result.exit_code == 0
    assert "Execução de" in result.output
    assert "Avaliação do período aqui." in result.output


def test_review_without_tasks(monkeypatch):
    monkeypatch.setattr(llm, "complete", lambda *a, **k: "não deveria ser chamado")
    result = runner.invoke(app, ["review"])
    assert result.exit_code == 1
    assert "nada para analisar" in result.output
