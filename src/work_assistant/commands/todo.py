"""`wa todo` — to-do diário (funciona sem o modelo)."""

import typer
from rich.console import Console
from rich.table import Table

from work_assistant import db, services

app = typer.Typer(help="To-do diário: adicionar, listar e concluir tarefas.")
console = Console()


def render_tasks(
    tasks: list[db.Task],
    title: str,
    projects: dict[int, str] | None = None,
    stages: dict[int, str] | None = None,
) -> None:
    if not tasks:
        console.print("[dim]Nenhuma tarefa para hoje. Use `wa todo add` ou `wa plan`.[/dim]")
        return
    projects = projects or {}
    stages = stages or {}
    table = Table(title=title)
    table.add_column("#", justify="right")
    table.add_column("Prio", justify="center")
    table.add_column("Esf", justify="center")
    table.add_column("Tarefa")
    table.add_column("Projeto")
    table.add_column("Tags")
    table.add_column("Prazo")
    table.add_column("Status")
    today = db.today()
    for t in tasks:
        status = "[green]✔ feita[/green]" if t.status == "done" else "pendente"
        prio = str(t.priority) if t.priority else "-"
        due = t.due_date or "-"
        if t.due_date and t.status != "done" and t.due_date < today:
            due = f"[red]{t.due_date} ![/red]"
        project = projects.get(t.project_id, "-") if t.project_id else "-"
        # A etapa entra na coluna Projeto em vez de ganhar coluna própria: a tabela
        # já é larga e o rich trunca células num terminal estreito.
        if t.stage_id in stages:
            project = f"{project} / {stages[t.stage_id]}"
        table.add_row(
            str(t.id), prio, t.effort or "-", t.title, project, t.tags or "-", due, status
        )
    console.print(table)


@app.command("add")
def add(
    title: str = typer.Argument(..., help="Descrição da tarefa"),
    day: str = typer.Option(None, "--day", "-d", help="Data (YYYY-MM-DD); padrão: hoje"),
    priority: int = typer.Option(None, "--priority", "-p", help="Prioridade (1 = mais alta)"),
    due: str = typer.Option(None, "--due", "-D", help="Prazo (YYYY-MM-DD)"),
    tags: list[str] = typer.Option(None, "--tag", "-t", help="Tag da tarefa (repetível)"),
    effort: str = typer.Option(None, "--effort", "-e", help="Esforço estimado: P, M ou G"),
    project: str = typer.Option(None, "--project", "-P", help="Número ou nome do projeto"),
    stage: str = typer.Option(
        None, "--stage", "-S", help="Etapa do projeto (posição, número ou nome); exige --project"
    ),
):
    """Adiciona uma tarefa ao to-do do dia."""
    conn = db.connect()
    project_id = None
    stage_id = None
    try:
        if project is not None:
            project_id = db.find_project(conn, project).id
        if stage is not None:
            if project_id is None:
                console.print("[red]Informe o projeto (--project) para escolher a etapa.[/red]")
                raise typer.Exit(1)
            stage_id = db.find_stage(conn, project_id, stage).id
        task = db.add_task(
            conn,
            title,
            project_id=project_id,
            day=day,
            priority=priority,
            due_date=due,
            tags=tags,
            effort=effort,
            stage_id=stage_id,
        )
    except (LookupError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    extras = ", ".join(
        part
        for part in (
            f"projeto: {project}" if project else "",
            f"etapa: {stage}" if stage else "",
            f"prazo {task.due_date}" if task.due_date else "",
            f"tags: {task.tags}" if task.tags else "",
            f"esforço {task.effort}" if task.effort else "",
        )
        if part
    )
    detail = f" ({extras})" if extras else ""
    console.print(
        f"[green]Tarefa #{task.id} adicionada:[/green] {task.title} ({task.day}){detail}"
    )


@app.command("list")
def list_(
    day: str = typer.Option(None, "--day", "-d", help="Data (YYYY-MM-DD); padrão: hoje"),
    pending: bool = typer.Option(False, "--pending", help="Só as pendentes"),
    project: str = typer.Option(None, "--project", "-P", help="Filtra por número ou nome do projeto"),
):
    """Lista as tarefas do dia."""
    conn = db.connect()
    services.ensure_routines(conn)
    tasks = db.list_tasks(conn, day=day, include_done=not pending)
    if project is not None:
        try:
            ref = db.find_project(conn, project)
        except LookupError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1)
        tasks = [t for t in tasks if t.project_id == ref.id]
    projects = {p.id: p.name for p in db.list_projects(conn, include_done=True, kind=None)}
    stages = {
        s.id: s.name
        for pid in {t.project_id for t in tasks if t.project_id}
        for s in db.list_stages(conn, pid)
    }
    render_tasks(tasks, f"To-do de {day or db.today()}", projects, stages)


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


@app.command("due")
def due(
    task_id: int = typer.Argument(..., help="Número da tarefa"),
    date: str = typer.Argument(..., help="Prazo (YYYY-MM-DD)"),
):
    """Define o prazo de uma tarefa."""
    conn = db.connect()
    try:
        task = db.set_task_due(conn, task_id, date)
    except (LookupError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]Prazo definido:[/green] {task.title} até {task.due_date}")


@app.command("tag")
def tag(
    task_id: int = typer.Argument(..., help="Número da tarefa"),
    tags: list[str] = typer.Argument(..., help="Tags da tarefa (substituem as atuais)"),
):
    """Define as tags de uma tarefa."""
    conn = db.connect()
    try:
        task = db.set_task_tags(conn, task_id, tags)
    except LookupError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]Tags definidas:[/green] {task.title} ({task.tags})")


@app.command("project")
def project(
    task_id: int = typer.Argument(..., help="Número da tarefa"),
    ref: str = typer.Argument(..., help="Número ou nome do projeto"),
):
    """Atribui uma tarefa a um projeto."""
    conn = db.connect()
    try:
        project_ = db.find_project(conn, ref)
        task = db.set_task_project(conn, task_id, project_.id)
    except LookupError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]Projeto definido:[/green] {task.title} -> {project_.name}")


@app.command("stage")
def stage(
    task_id: int = typer.Argument(..., help="Número da tarefa"),
    ref: str = typer.Argument(..., help="Número ou nome do projeto"),
    stage_ref: str = typer.Argument(..., help="Posição, número ou nome da etapa"),
):
    """Vincula uma tarefa a uma etapa do projeto (o projeto vem junto)."""
    conn = db.connect()
    try:
        project_ = db.find_project(conn, ref)
        stage_ = db.find_stage(conn, project_.id, stage_ref)
        task = db.set_task_stage(conn, task_id, stage_.id)
    except LookupError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    console.print(
        f"[green]Etapa definida:[/green] {task.title} -> {project_.name} / {stage_.name}"
    )
