"""`wa checkpoint` — check-in de progresso de um projeto, avaliado pelo modelo."""

import typer
from rich.console import Console
from rich.markdown import Markdown

from work_assistant import db, services

# Registrado como comando direto em cli.py (não `add_typer`): como sub-typer o Typer
# cria um Click Group, e um Group trata o que vem depois do argumento posicional como
# nome de subcomando — `wa checkpoint Janela -S 2` viraria erro de uso.
console = Console()


def _pick_stage(conn, project: db.Project, stage_ref: str | None) -> db.Stage | None:
    """Resolve a etapa por `--stage`, ou pergunta quando o projeto tem etapas."""
    stages = db.list_stages(conn, project.id)
    if not stages:
        return None  # projeto sem etapas: fluxo idêntico ao de antes
    if stage_ref is not None:
        try:
            return db.find_stage(conn, project.id, stage_ref)
        except LookupError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1)
    console.print("[dim]Etapas:[/dim]")
    for s in stages:
        marca = "✔" if s.status == "done" else " "
        prazo = f" (prazo {s.deadline})" if s.deadline else ""
        console.print(f"  [{marca}] {s.position}. {s.name}{prazo}")
    escolha = typer.prompt("Qual etapa? (Enter = o projeto todo)", default="", show_default=False)
    if not escolha.strip():
        return None
    try:
        return db.find_stage(conn, project.id, escolha.strip())
    except LookupError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)


def checkpoint(
    ref: str = typer.Argument(None, help="Número ou nome do projeto (opcional se houver só um ativo)"),
    stage_ref: str = typer.Option(
        None, "--stage", "-S", help="Avaliar uma etapa específica (posição, número ou nome)"
    ),
):
    """Registra um checkpoint: você relata o progresso, o modelo avalia contra o objetivo."""
    conn = db.connect()
    try:
        if ref:
            project = db.find_project(conn, ref)
        else:
            projects = db.list_projects(conn)
            if len(projects) != 1:
                console.print(
                    "[red]Informe o projeto:[/red] `wa checkpoint <nome ou nº>`. "
                    "Veja os ativos com `wa project list`."
                )
                raise typer.Exit(1)
            project = projects[0]
    except LookupError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    console.print(f"[bold]Checkpoint — {project.name}[/bold]")
    console.print(f"[dim]Objetivo: {project.goal}[/dim]\n")

    stage = _pick_stage(conn, project, stage_ref)
    if stage:
        console.print(f"[dim]Etapa: {stage.name}[/dim]")
        if stage.done_criteria:
            console.print(f"[dim]Pronto quando: {stage.done_criteria}[/dim]")
        console.print()

    progress = typer.prompt("Como está o progresso? (o que avançou, o que travou, o que falta)")

    with console.status("Avaliando progresso..."):
        result = services.run_checkpoint(conn, project, progress, stage=stage)

    console.print()
    console.print(Markdown(result["markdown"]))
    console.print("\n[dim]Checkpoint salvo.[/dim]")
