"""`wa todo` — to-do diário (funciona sem o modelo)."""

import typer
from rich.console import Console
from rich.table import Table

from work_assistant import db

app = typer.Typer(help="To-do diário: adicionar, listar e concluir tarefas.")
console = Console()


def render_tasks(tasks: list[db.Task], title: str) -> None:
    if not tasks:
        console.print("[dim]Nenhuma tarefa para hoje. Use `wa todo add` ou `wa plan`.[/dim]")
        return
    table = Table(title=title)
    table.add_column("#", justify="right")
    table.add_column("Prio", justify="center")
    table.add_column("Tarefa")
    table.add_column("Status")
    for t in tasks:
        status = "[green]✔ feita[/green]" if t.status == "done" else "pendente"
        prio = str(t.priority) if t.priority else "-"
        table.add_row(str(t.id), prio, t.title, status)
    console.print(table)


@app.command("add")
def add(
    title: str = typer.Argument(..., help="Descrição da tarefa"),
    day: str = typer.Option(None, "--day", "-d", help="Data (YYYY-MM-DD); padrão: hoje"),
    priority: int = typer.Option(None, "--priority", "-p", help="Prioridade (1 = mais alta)"),
):
    """Adiciona uma tarefa ao to-do do dia."""
    conn = db.connect()
    task = db.add_task(conn, title, day=day, priority=priority)
    console.print(f"[green]Tarefa #{task.id} adicionada:[/green] {task.title} ({task.day})")


@app.command("list")
def list_(
    day: str = typer.Option(None, "--day", "-d", help="Data (YYYY-MM-DD); padrão: hoje"),
    pending: bool = typer.Option(False, "--pending", help="Só as pendentes"),
):
    """Lista as tarefas do dia."""
    conn = db.connect()
    tasks = db.list_tasks(conn, day=day, include_done=not pending)
    render_tasks(tasks, f"To-do de {day or db.today()}")


@app.command("done")
def done(task_id: int = typer.Argument(..., help="Número da tarefa")):
    """Marca uma tarefa como concluída."""
    conn = db.connect()
    try:
        task = db.complete_task(conn, task_id)
    except LookupError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]✔ Concluída:[/green] {task.title}")
