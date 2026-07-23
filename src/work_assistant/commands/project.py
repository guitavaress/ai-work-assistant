"""`wa project` — projetos/entregas acompanhados ao longo de uma ou mais sprints."""

import typer
from rich.console import Console
from rich.table import Table

from work_assistant import db

app = typer.Typer(help="Projetos: entregas com objetivo definido, acompanhadas por checkpoints.")
console = Console()


@app.command("add")
def add(
    name: str = typer.Argument(..., help="Nome curto do projeto"),
    goal: str = typer.Option(..., "--goal", "-g", help="Objetivo da entrega (o que é 'pronto')"),
    deadline: str = typer.Option(None, "--deadline", "-D", help="Data-alvo da entrega (YYYY-MM-DD)"),
):
    """Registra um projeto com o objetivo da entrega."""
    conn = db.connect()
    try:
        project = db.add_project(conn, name, goal, deadline=deadline)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]Projeto #{project.id} criado:[/green] {project.name}")
    console.print(f"[dim]Objetivo: {project.goal}[/dim]")
    if project.deadline:
        console.print(f"[dim]Prazo: {project.deadline}[/dim]")


@app.command("list")
def list_(
    all: bool = typer.Option(False, "--all", "-a", help="Inclui projetos concluídos"),
):
    """Lista os projetos ativos."""
    conn = db.connect()
    projects = db.list_projects(conn, include_done=all)
    if not projects:
        console.print("[dim]Nenhum projeto. Use `wa project add`.[/dim]")
        return
    table = Table(title="Projetos")
    table.add_column("#", justify="right")
    table.add_column("Nome")
    table.add_column("Objetivo")
    table.add_column("Prazo")
    table.add_column("Tarefas")
    table.add_column("Status")
    today = db.today()
    for p in projects:
        status = "[green]concluído[/green]" if p.status == "done" else "ativo"
        deadline = p.deadline or "-"
        if p.deadline and p.status != "done" and p.deadline < today:
            deadline = f"[red]{p.deadline} ![/red]"
        project_tasks = db.list_tasks_by_project(conn, p.id)
        done = sum(1 for t in project_tasks if t.status == "done")
        tasks_count = f"{done}/{len(project_tasks)}" if project_tasks else "-"
        table.add_row(str(p.id), p.name, p.goal, deadline, tasks_count, status)
    console.print(table)


@app.command("deadline")
def deadline(
    ref: str = typer.Argument(..., help="Número ou nome do projeto"),
    date: str = typer.Argument(..., help="Data-alvo da entrega (YYYY-MM-DD)"),
):
    """Define o prazo de entrega de um projeto."""
    conn = db.connect()
    try:
        project = db.find_project(conn, ref)
        project = db.set_project_deadline(conn, project.id, date)
    except (LookupError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]Prazo definido:[/green] {project.name} até {project.deadline}")


@app.command("done")
def done(ref: str = typer.Argument(..., help="Número ou nome do projeto")):
    """Marca um projeto como concluído."""
    conn = db.connect()
    try:
        project = db.find_project(conn, ref)
        db.complete_project(conn, project.id)
    except LookupError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]✔ Projeto concluído:[/green] {project.name}")
