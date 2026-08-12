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


# --- Etapas -----------------------------------------------------------------


def _projeto_com_etapas():
    runner.invoke(app, ["project", "add", "Janela", "--goal", "fechar comissões"])
    runner.invoke(app, ["project", "stage", "add", "Janela", "Extrair base", "-D", "2030-08-01"])
    runner.invoke(
        app,
        ["project", "stage", "add", "Janela", "Reconciliar", "-c", "diferença < 0,01%"],
    )


def test_project_stage_add_and_list():
    _projeto_com_etapas()
    result = runner.invoke(app, ["project", "stage", "list", "Janela"])
    assert result.exit_code == 0
    assert "Extrair base" in result.output
    assert "Reconciliar" in result.output
    assert "2030-08-01" in result.output


def test_project_stage_add_invalid_project():
    result = runner.invoke(app, ["project", "stage", "add", "inexistente", "Etapa"])
    assert result.exit_code == 1
    assert "não encontrado" in result.output


def test_project_stage_due_and_criteria():
    _projeto_com_etapas()
    result = runner.invoke(app, ["project", "stage", "due", "Janela", "1", "2030-09-01"])
    assert result.exit_code == 0
    assert "2030-09-01" in result.output

    result = runner.invoke(
        app, ["project", "stage", "criteria", "Janela", "1", "arquivo na landing"]
    )
    assert result.exit_code == 0
    assert "arquivo na landing" in result.output


def test_project_stage_due_invalid_date():
    _projeto_com_etapas()
    result = runner.invoke(app, ["project", "stage", "due", "Janela", "1", "setembro"])
    assert result.exit_code == 1
    assert "inválida" in result.output


def test_project_stage_done():
    _projeto_com_etapas()
    result = runner.invoke(app, ["project", "stage", "done", "Janela", "Extrair base"])
    assert result.exit_code == 0
    assert "Etapa concluída" in result.output

    result = runner.invoke(app, ["project", "stage", "done", "Janela", "2"])
    assert "Todas as etapas" in result.output


def test_project_stage_missing_stage():
    _projeto_com_etapas()
    result = runner.invoke(app, ["project", "stage", "done", "Janela", "inexistente"])
    assert result.exit_code == 1
    assert "não encontrada" in result.output


def test_todo_add_with_stage(monkeypatch):
    _projeto_com_etapas()
    result = runner.invoke(
        app, ["todo", "add", "Baixar arquivo", "-P", "Janela", "-S", "1"]
    )
    assert result.exit_code == 0
    assert "etapa: 1" in result.output

    # A etapa divide a coluna Projeto; num terminal de 80 colunas o rich trunca.
    monkeypatch.setenv("COLUMNS", "200")
    result = runner.invoke(app, ["todo", "list"])
    assert "Janela / Extrair base" in result.output


def test_todo_add_stage_without_project():
    _projeto_com_etapas()
    result = runner.invoke(app, ["todo", "add", "Baixar arquivo", "-S", "1"])
    assert result.exit_code == 1
    assert "--project" in result.output


def test_todo_stage_command():
    _projeto_com_etapas()
    runner.invoke(app, ["todo", "add", "Baixar arquivo"])
    result = runner.invoke(app, ["todo", "stage", "1", "Janela", "Extrair base"])
    assert result.exit_code == 0
    assert "Janela / Extrair base" in result.output


# --- Rotinas ----------------------------------------------------------------


def _janela():
    return runner.invoke(
        app,
        ["routine", "add", "Janela de Comissões", "-g", "fechar no SLA",
         "-c", "monthly", "-o", "1", "-s", "5"],
    )


def test_routine_add_and_list(monkeypatch):
    monkeypatch.setenv("COLUMNS", "200")
    result = _janela()
    assert result.exit_code == 0
    assert "Rotina #1 criada" in result.output
    assert "mensal, dia 1 (janela 5d)" in result.output

    result = runner.invoke(app, ["routine", "list"])
    assert result.exit_code == 0
    assert "Janela de Comissões" in result.output


def test_routine_add_invalid_cadence():
    result = runner.invoke(
        app, ["routine", "add", "X", "-g", "meta", "-c", "diaria", "-o", "1"]
    )
    assert result.exit_code == 1
    assert "Cadência inválida" in result.output


def test_routine_add_invalid_anchor():
    result = runner.invoke(
        app, ["routine", "add", "X", "-g", "meta", "-c", "weekly", "-o", "9"]
    )
    assert result.exit_code == 1
    assert "Dia de abertura inválido" in result.output


def test_routine_steps_uses_the_editor(monkeypatch):
    import click

    _janela()
    buffer = (
        "# comentário ignorado\n"
        "Extrair base | 0 | arquivo na landing\n"
        "Reconciliar | 1 | diferença < 0,01%\n"
        "Publicar\n"
    )
    monkeypatch.setattr(click, "edit", lambda *a, **k: buffer)
    result = runner.invoke(app, ["routine", "steps", "Janela de Comissões"])
    assert result.exit_code == 0
    assert "3 etapa(s)" in result.output
    assert "1. Extrair base" in result.output
    assert "3. Publicar" in result.output


def test_routine_steps_aborted_editor_changes_nothing(monkeypatch):
    import click

    _janela()
    runner.invoke(app, ["routine", "step", "Janela de Comissões", "Extrair base"])
    monkeypatch.setattr(click, "edit", lambda *a, **k: None)
    result = runner.invoke(app, ["routine", "steps", "Janela de Comissões"])
    assert "Nada alterado" in result.output

    result = runner.invoke(app, ["routine", "show", "Janela de Comissões"])
    assert "Extrair base" in result.output


def test_routine_steps_invalid_offset(monkeypatch):
    import click

    _janela()
    monkeypatch.setattr(click, "edit", lambda *a, **k: "Extrair | amanhã | x\n")
    result = runner.invoke(app, ["routine", "steps", "Janela de Comissões"])
    assert result.exit_code == 1
    assert "Offset inválido" in result.output


def test_routine_step_add_and_show():
    _janela()
    result = runner.invoke(
        app,
        ["routine", "step", "Janela de Comissões", "Reconciliar", "-o", "1",
         "-c", "diferença < 0,01%"],
    )
    assert result.exit_code == 0
    assert "Etapa 1 adicionada" in result.output

    result = runner.invoke(app, ["routine", "show", "Janela de Comissões"])
    assert "Reconciliar" in result.output
    assert "abertura +1d" in result.output


def test_routine_run_materializes_a_cycle():
    _janela()
    runner.invoke(app, ["routine", "step", "Janela de Comissões", "Extrair base"])
    result = runner.invoke(app, ["routine", "run", "Janela de Comissões", "-p", "2026-08"])
    assert result.exit_code == 0
    assert "Janela de Comissões — 2026-08" in result.output
    assert "2026-08-05" in result.output  # abertura 01/08 + 4 dias

    # o ciclo não polui a lista de projetos, mas aparece com --routines
    assert "Janela de Comissões" not in runner.invoke(app, ["project", "list"]).output
    assert "⟳" in runner.invoke(app, ["project", "list", "-r"]).output


def test_routine_run_on_a_closed_period_warns_instead_of_pretending():
    """O período comporta um ciclo só: `run` devolve o fechado, e precisa dizer isso."""
    _janela()
    runner.invoke(app, ["routine", "step", "Janela de Comissões", "Extrair base"])
    runner.invoke(app, ["routine", "run", "Janela de Comissões", "-p", "2026-08"])
    runner.invoke(app, ["routine", "close", "Janela de Comissões"])

    result = runner.invoke(app, ["routine", "run", "Janela de Comissões", "-p", "2026-08"])
    assert result.exit_code == 0
    assert "já foi fechado" in result.output
    assert "nenhum ciclo novo foi criado" in result.output


def test_routine_run_invalid_period():
    _janela()
    result = runner.invoke(app, ["routine", "run", "Janela de Comissões", "-p", "agosto"])
    assert result.exit_code == 1
    assert "Período inválido" in result.output


def test_routine_close_warns_about_pending_stages():
    _janela()
    runner.invoke(app, ["routine", "step", "Janela de Comissões", "Extrair base"])
    runner.invoke(app, ["routine", "run", "Janela de Comissões", "-p", "2026-08"])
    result = runner.invoke(app, ["routine", "close", "Janela de Comissões"])
    assert result.exit_code == 0
    assert "Etapas ainda pendentes: Extrair base" in result.output
    assert "Ciclo fechado" in result.output


def test_routine_close_without_open_cycle():
    _janela()
    result = runner.invoke(app, ["routine", "close", "Janela de Comissões"])
    assert result.exit_code == 1
    assert "Nenhum ciclo aberto" in result.output


def test_routine_archive():
    _janela()
    result = runner.invoke(app, ["routine", "archive", "Janela de Comissões"])
    assert result.exit_code == 0
    assert runner.invoke(app, ["routine", "list"]).output.strip().startswith("Nenhuma rotina")


def test_routine_missing():
    result = runner.invoke(app, ["routine", "show", "inexistente"])
    assert result.exit_code == 1
    assert "não encontrada" in result.output


# --- Checkpoint com etapa ---------------------------------------------------


def _mock_llm(monkeypatch):
    monkeypatch.setattr(
        llm,
        "structured",
        lambda *a, **k: {
            "situacao": "Reconciliação parada.",
            "riscos": "Critério não verificado.",
            "proximo_passo": ["Rodar o batimento"],
            "vereditos": [
                {"etapa": "Reconciliar", "veredito": "nao_atende",
                 "justificativa": "sem batimento"}
            ],
            "status": "em risco",
            "resumo": "Em risco — reconciliação sem batimento.",
        },
    )


def test_checkpoint_with_stage_option(monkeypatch):
    _mock_llm(monkeypatch)
    _projeto_com_etapas()
    result = runner.invoke(
        app, ["checkpoint", "Janela", "-S", "2"], input="avancei no de-para\n"
    )
    assert result.exit_code == 0
    assert "Etapa: Reconciliar" in result.output
    assert "Pronto quando: diferença < 0,01%" in result.output
    assert "Reconciliação parada." in result.output


def test_checkpoint_asks_for_the_stage(monkeypatch):
    _mock_llm(monkeypatch)
    _projeto_com_etapas()
    # Enter na pergunta da etapa = avaliar o projeto todo
    result = runner.invoke(app, ["checkpoint", "Janela"], input="\nrelato do dia\n")
    assert result.exit_code == 0
    assert "Qual etapa?" in result.output
    assert "Reconciliação parada." in result.output


def test_checkpoint_with_invalid_stage(monkeypatch):
    _mock_llm(monkeypatch)
    _projeto_com_etapas()
    result = runner.invoke(app, ["checkpoint", "Janela", "-S", "inexistente"])
    assert result.exit_code == 1
    assert "não encontrada" in result.output


def test_checkpoint_without_stages_keeps_the_old_flow(monkeypatch):
    _mock_llm(monkeypatch)
    runner.invoke(app, ["project", "add", "Sem etapas", "--goal", "meta"])
    result = runner.invoke(app, ["checkpoint", "Sem etapas"], input="relato\n")
    assert result.exit_code == 0
    assert "Qual etapa?" not in result.output
    assert "Reconciliação parada." in result.output


def test_checkpoint_prints_stage_verdicts(monkeypatch):
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setattr(
        llm,
        "structured",
        lambda *a, **k: {
            "situacao": "Reconciliação parada.",
            "riscos": "Critério não verificado.",
            "proximo_passo": ["Rodar o batimento"],
            "status": "em risco",
            "resumo": "Em risco.",
            "vereditos": [
                {"etapa": "Extrair base", "veredito": "atende", "justificativa": "arquivo chegou"},
                {"etapa": "Reconciliar", "veredito": "nao_atende", "justificativa": "sem batimento"},
            ],
        },
    )
    _projeto_com_etapas()
    result = runner.invoke(app, ["checkpoint", "Janela"], input="\nrelato\n")
    assert result.exit_code == 0
    assert "atende" in result.output
    assert "não atende" in result.output
    assert "sem batimento" in result.output
