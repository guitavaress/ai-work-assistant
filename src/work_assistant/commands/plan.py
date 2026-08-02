"""`wa plan` — monta o to-do do dia com ajuda do modelo."""

import typer
from rich.console import Console

from work_assistant import db, services
from work_assistant.commands.todo import render_tasks

app = typer.Typer()
console = Console()


@app.callback(invoke_without_command=True)
def plan():
    """Conversa curta que transforma seu relato do dia em um to-do priorizado."""
    conn = db.connect()
    # Antes do suggest_plan: o ciclo aberto hoje precisa entrar no contexto do modelo.
    services.ensure_routines(conn)
    relato = typer.prompt("O que você tem para hoje? (reuniões, entregas, pendências)")

    with console.status("Planejando o dia..."):
        suggested = services.suggest_plan(conn, relato)

    if not suggested:
        console.print("[yellow]O modelo não sugeriu tarefas. Tente detalhar mais o relato.[/yellow]")
        raise typer.Exit(1)

    console.print("\n[bold]Sugestão de to-do:[/bold]")
    for t in suggested:
        console.print(f"  {t['priority']}. {t['title']}")

    if not typer.confirm("\nSalvar essas tarefas no to-do de hoje?", default=True):
        console.print("[dim]Nada salvo.[/dim]")
        raise typer.Exit()

    services.save_plan(conn, suggested)
    render_tasks(db.list_tasks(conn), f"To-do de {db.today()}")
