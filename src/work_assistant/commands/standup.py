"""`wa standup` — gera a fala da daily a partir do histórico."""

import typer
from rich.console import Console
from rich.markdown import Markdown

from work_assistant import db, services

app = typer.Typer()
console = Console()


@app.callback(invoke_without_command=True)
def standup(
    days: int = typer.Option(1, "--days", "-n", help="Quantos dias para trás olhar (padrão: 1)"),
):
    """Resume o que foi feito e o que vem hoje, no formato de daily/standup."""
    conn = db.connect()
    try:
        with console.status("Preparando o standup..."):
            result = services.run_standup(conn, days)
    except LookupError as e:
        console.print(f"[yellow]{e}[/yellow]")
        raise typer.Exit(1)
    console.print(Markdown(result["markdown"]))
