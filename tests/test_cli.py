import pytest
from typer.testing import CliRunner

from work_assistant import config
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


def test_todo_done_missing_task():
    result = runner.invoke(app, ["todo", "done", "42"])
    assert result.exit_code == 1
    assert "não encontrada" in result.output


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
