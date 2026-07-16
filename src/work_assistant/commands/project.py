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
):
    """Registra um projeto com o objetivo da entrega."""
    conn = db.connect()
    project = db.add_project(conn, name, goal)
    console.print(f"[green]Projeto #{project.id} criado:[/green] {project.name}")
    console.print(f"[dim]Objetivo: {project.goal}[/dim]")


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
    table.add_column("Status")
    for p in projects:
        status = "[green]concluído[/green]" if p.status == "done" else "ativo"
        table.add_row(str(p.id), p.name, p.goal, status)
    console.print(table)


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
