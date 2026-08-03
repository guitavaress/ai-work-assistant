"""`wa project` — projetos/entregas acompanhados ao longo de uma ou mais sprints."""

import typer
from rich.console import Console
from rich.table import Table

from work_assistant import db, services

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
    routines: bool = typer.Option(
        False, "--routines", "-r", help="Inclui os ciclos das rotinas"
    ),
):
    """Lista os projetos ativos."""
    conn = db.connect()
    services.ensure_routines(conn)
    projects = db.list_projects(conn, include_done=all, kind=None if routines else "project")
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
        progress = db.project_progress(conn, p.id)
        tasks_count = f"{progress['done']}/{progress['total']}" if progress["total"] else "-"
        name = f"⟳ {p.name}" if p.kind == "routine_run" else p.name
        table.add_row(str(p.id), name, p.goal, deadline, tasks_count, status)
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
def done(
    ref: str = typer.Argument(..., help="Número ou nome do projeto"),
    on: str = typer.Option(
        None, "--on", help="Data do fechamento (YYYY-MM-DD); padrão: agora"
    ),
):
    """Marca um projeto como concluído."""
    conn = db.connect()
    try:
        project = db.find_project(conn, ref)
        project = db.complete_project(conn, project.id, closed_on=on)
    except (LookupError, ValueError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]✔ Projeto concluído:[/green] {project.name} ({project.done_at[:10]})")


# --- Etapas -----------------------------------------------------------------

stage_app = typer.Typer(help="Etapas: entregáveis intermediários do projeto, com prazo próprio.")
app.add_typer(stage_app, name="stage")


def _resolve(conn, ref: str, stage_ref: str | None = None):
    """Resolve projeto (e opcionalmente etapa), saindo com erro em PT-BR."""
    try:
        project = db.find_project(conn, ref)
        stage = db.find_stage(conn, project.id, stage_ref) if stage_ref is not None else None
    except LookupError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    return project, stage


@stage_app.command("add")
def stage_add(
    ref: str = typer.Argument(..., help="Número ou nome do projeto"),
    name: str = typer.Argument(..., help="Nome da etapa"),
    due: str = typer.Option(None, "--due", "-D", help="Prazo da etapa (YYYY-MM-DD)"),
    criteria: str = typer.Option(
        None, "--criteria", "-c", help="Critério de pronto (o que precisa ser verdade)"
    ),
    position: int = typer.Option(None, "--position", "-n", help="Posição na ordem (padrão: fim)"),
):
    """Adiciona uma etapa ao projeto."""
    conn = db.connect()
    project, _ = _resolve(conn, ref)
    try:
        stage = db.add_stage(
            conn, project.id, name, deadline=due, done_criteria=criteria, position=position
        )
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    detail = f" (prazo {stage.deadline})" if stage.deadline else ""
    console.print(
        f"[green]Etapa {stage.position} criada:[/green] {stage.name}{detail} — {project.name}"
    )


@stage_app.command("list")
def stage_list(
    ref: str = typer.Argument(..., help="Número ou nome do projeto"),
    all: bool = typer.Option(True, "--all/--pending", "-a", help="Inclui as etapas concluídas"),
):
    """Lista as etapas do projeto com prazo, progresso e critério de pronto."""
    conn = db.connect()
    project, _ = _resolve(conn, ref)
    stages = db.list_stages(conn, project.id, include_done=all)
    if not stages:
        console.print(f"[dim]Nenhuma etapa em {project.name}. Use `wa project stage add`.[/dim]")
        return
    table = Table(title=f"Etapas — {project.name}")
    table.add_column("#", justify="right")
    table.add_column("Etapa")
    table.add_column("Prazo")
    table.add_column("Tarefas", justify="center")
    table.add_column("Pronto quando")
    table.add_column("Status")
    today = db.today()
    for s in stages:
        deadline = s.deadline or "-"
        if s.deadline and s.status != "done" and s.deadline < today:
            deadline = f"[red]{s.deadline} ![/red]"
        progress = db.stage_progress(conn, s.id)
        tasks_count = f"{progress['done']}/{progress['total']}" if progress["total"] else "-"
        status = "[green]✔ feita[/green]" if s.status == "done" else "pendente"
        table.add_row(
            str(s.position), s.name, deadline, tasks_count, s.done_criteria or "-", status
        )
    console.print(table)


@stage_app.command("due")
def stage_due(
    ref: str = typer.Argument(..., help="Número ou nome do projeto"),
    stage_ref: str = typer.Argument(..., help="Posição, número ou nome da etapa"),
    date: str = typer.Argument(..., help="Prazo da etapa (YYYY-MM-DD)"),
):
    """Define o prazo de uma etapa."""
    conn = db.connect()
    project, stage = _resolve(conn, ref, stage_ref)
    try:
        stage = db.set_stage_deadline(conn, stage.id, date)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]Prazo definido:[/green] {stage.name} até {stage.deadline}")


@stage_app.command("criteria")
def stage_criteria(
    ref: str = typer.Argument(..., help="Número ou nome do projeto"),
    stage_ref: str = typer.Argument(..., help="Posição, número ou nome da etapa"),
    text: str = typer.Argument(..., help="O que precisa ser verdade para a etapa estar pronta"),
):
    """Define o critério de pronto de uma etapa (é o que o checkpoint passa a avaliar)."""
    conn = db.connect()
    project, stage = _resolve(conn, ref, stage_ref)
    stage = db.set_stage_criteria(conn, stage.id, text)
    console.print(f"[green]Critério definido:[/green] {stage.name} — pronto quando: {stage.done_criteria}")


@stage_app.command("done")
def stage_done(
    ref: str = typer.Argument(..., help="Número ou nome do projeto"),
    stage_ref: str = typer.Argument(..., help="Posição, número ou nome da etapa"),
):
    """Marca uma etapa como concluída."""
    conn = db.connect()
    project, stage = _resolve(conn, ref, stage_ref)
    if stage.done_criteria:
        console.print(f"[dim]Critério: {stage.done_criteria}[/dim]")
    stage = db.complete_stage(conn, stage.id)
    console.print(f"[green]✔ Etapa concluída:[/green] {stage.name} — {project.name}")
    restantes = db.list_stages(conn, project.id, include_done=False)
    if not restantes:
        console.print(
            f"[dim]Todas as etapas de {project.name} estão fechadas."
            " Use `wa project done` para concluir.[/dim]"
        )
