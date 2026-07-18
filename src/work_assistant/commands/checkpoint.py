"""`wa checkpoint` — check-in de progresso de um projeto, avaliado pelo modelo."""

import typer
from rich.console import Console
from rich.markdown import Markdown

from work_assistant import db, services

app = typer.Typer()
console = Console()


@app.callback(invoke_without_command=True)
def checkpoint(
    ref: str = typer.Argument(None, help="Número ou nome do projeto (opcional se houver só um ativo)"),
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
    progress = typer.prompt("Como está o progresso? (o que avançou, o que travou, o que falta)")

    with console.status("Avaliando progresso..."):
        result = services.run_checkpoint(conn, project, progress)

    console.print()
    console.print(Markdown(result["markdown"]))
    console.print("\n[dim]Checkpoint salvo.[/dim]")
