"""`wa routine` — trabalho recorrente (janelas, fechamentos, rotinas de operação).

Rotina é o molde: cadência, janela e checklist. Cada período vira um *ciclo*, que é
materializado sozinho quando a janela abre e reaproveita etapas, tarefas e checkpoints.
"""

from datetime import date

import click  # typer não reexporta `edit`; é o editor do click
import typer
from rich.console import Console
from rich.table import Table

from work_assistant import db, schedule, services

app = typer.Typer(help="Rotinas: trabalho recorrente com janela e SLA (ex.: fechamento mensal).")
console = Console()

_STEPS_HEADER = """\
# Uma etapa por linha:  nome | offset em dias | critério de pronto
# offset = dias após a abertura do ciclo. Linhas começando com # são ignoradas.
# A ordem das linhas define a ordem das etapas. Salve e feche para aplicar.
"""


def _find(conn, ref: str) -> db.Routine:
    try:
        return db.find_routine(conn, ref)
    except LookupError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)


def _render_steps(steps: list[db.RoutineStep]) -> str:
    lines = [f"{s.name} | {s.offset_days} | {s.done_criteria or ''}".rstrip(" |") for s in steps]
    return _STEPS_HEADER + "\n".join(lines) + "\n"


def _parse_steps(text: str) -> list[dict]:
    """Lê o buffer do editor: 1 a 3 campos por linha, separados por `|`."""
    steps = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        name = parts[0]
        if not name:
            continue
        try:
            offset = int(parts[1]) if len(parts) > 1 and parts[1] else 0
        except ValueError:
            raise ValueError(f"Offset inválido em '{line}': use um número de dias") from None
        steps.append(
            {
                "name": name,
                "offset_days": offset,
                "done_criteria": parts[2] if len(parts) > 2 and parts[2] else None,
            }
        )
    return steps


@app.command("add")
def add(
    name: str = typer.Argument(..., help="Nome da rotina (ex.: 'Janela de Comissões')"),
    goal: str = typer.Option(..., "--goal", "-g", help="O que significa a rotina ter rodado bem"),
    cadence: str = typer.Option("monthly", "--cadence", "-c", help="daily, weekly ou monthly"),
    opens: int = typer.Option(
        0,
        "--opens",
        "-o",
        help="Mensal: dia do mês (-1 = último). Semanal: 1 = segunda a 7 = domingo. Diária: não use",
    ),
    sla_days: int = typer.Option(
        1,
        "--sla-days",
        "-s",
        help="Duração da janela em dias, contando o dia de abertura (abre dia 1, fecha dia 5 = 5)",
    ),
):
    """Cadastra uma rotina. Depois use `wa routine steps` para montar o checklist."""
    conn = db.connect()
    try:
        routine = db.add_routine(conn, name, goal, cadence, opens, sla_days=sla_days)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]Rotina #{routine.id} criada:[/green] {routine.name}")
    console.print(f"[dim]Cadência: {schedule.describe(cadence, opens, sla_days)}[/dim]")
    console.print(f"[dim]Próxima abertura: {services.routine_view(conn, routine)['next_open']}[/dim]")
    console.print(f"[dim]Monte o checklist com `wa routine steps \"{routine.name}\"`.[/dim]")


@app.command("list")
def list_(
    all: bool = typer.Option(False, "--all", "-a", help="Inclui as rotinas arquivadas"),
):
    """Lista as rotinas e o estado do ciclo mais recente."""
    conn = db.connect()
    services.ensure_routines(conn)
    routines = db.list_routines(conn, include_archived=all)
    if not routines:
        console.print("[dim]Nenhuma rotina. Use `wa routine add`.[/dim]")
        return
    table = Table(title="Rotinas")
    table.add_column("#", justify="right")
    table.add_column("Rotina")
    table.add_column("Cadência")
    table.add_column("Etapas", justify="center")
    table.add_column("Ciclo atual")
    table.add_column("Status")
    for r in routines:
        view = services.routine_view(conn, r)
        if view["runs"]:
            last = view["runs"][-1]
            stages = last["stages"]
            estado = (
                "concluído"
                if last["project"].status == "done"
                else f"{stages['done']}/{stages['total']} etapas"
            )
            current = f"{last['project'].period} — {estado}"
        else:
            current = f"abre {view['next_open']}"
        status = "arquivada" if r.status == "archived" else "ativa"
        table.add_row(
            str(r.id), r.name, view["cadence"], str(len(view["steps"])), current, status
        )
    console.print(table)


@app.command("show")
def show(ref: str = typer.Argument(..., help="Número ou nome da rotina")):
    """Detalha uma rotina: checklist, ciclos já rodados e próxima abertura."""
    conn = db.connect()
    services.ensure_routines(conn)
    view = services.routine_view(conn, _find(conn, ref))
    routine = view["routine"]

    console.print(f"[bold]{routine.name}[/bold]")
    console.print(f"[dim]{routine.goal}[/dim]")
    console.print(f"[dim]{view['cadence']} — próxima abertura: {view['next_open']}[/dim]\n")

    if view["steps"]:
        steps = Table(title="Checklist")
        steps.add_column("#", justify="right")
        steps.add_column("Etapa")
        steps.add_column("Prazo", justify="center")
        steps.add_column("Pronto quando")
        for s in view["steps"]:
            steps.add_row(
                str(s.position), s.name, f"abertura +{s.offset_days}d", s.done_criteria or "-"
            )
        console.print(steps)
    else:
        console.print(f"[dim]Sem checklist. Use `wa routine steps \"{routine.name}\"`.[/dim]")

    if view["runs"]:
        runs = Table(title="Ciclos")
        runs.add_column("Período")
        runs.add_column("Prazo")
        runs.add_column("Etapas", justify="center")
        runs.add_column("Tarefas", justify="center")
        runs.add_column("Status")
        today = db.today()
        for run in view["runs"]:
            p = run["project"]
            deadline = p.deadline or "-"
            if p.deadline and p.status == "active" and p.deadline < today:
                deadline = f"[red]{p.deadline} ![/red]"
            runs.add_row(
                p.period,
                deadline,
                f"{run['stages']['done']}/{run['stages']['total']}",
                f"{run['tasks']['done']}/{run['tasks']['total']}",
                "[green]concluído[/green]" if p.status == "done" else "aberto",
            )
        console.print(runs)


@app.command("steps")
def steps(ref: str = typer.Argument(..., help="Número ou nome da rotina")):
    """Edita o checklist inteiro no $EDITOR (substitui o que existia)."""
    conn = db.connect()
    routine = _find(conn, ref)
    edited = click.edit(_render_steps(db.list_routine_steps(conn, routine.id)))
    if edited is None:
        console.print("[dim]Nada alterado.[/dim]")
        return
    try:
        parsed = _parse_steps(edited)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    saved = db.replace_routine_steps(conn, routine.id, parsed)
    console.print(f"[green]Checklist salvo:[/green] {len(saved)} etapa(s) em {routine.name}")
    for s in saved:
        console.print(f"  {s.position}. {s.name} [dim](abertura +{s.offset_days}d)[/dim]")
    console.print("[dim]Ciclos já materializados não mudam — só os próximos.[/dim]")


@app.command("step")
def step_add(
    ref: str = typer.Argument(..., help="Número ou nome da rotina"),
    name: str = typer.Argument(..., help="Nome da etapa"),
    offset: int = typer.Option(0, "--offset", "-o", help="Dias após a abertura do ciclo"),
    criteria: str = typer.Option(None, "--criteria", "-c", help="Critério de pronto"),
):
    """Acrescenta uma etapa ao fim do checklist (caminho incremental/scriptável)."""
    conn = db.connect()
    routine = _find(conn, ref)
    step = db.add_routine_step(
        conn, routine.id, name, offset_days=offset, done_criteria=criteria
    )
    console.print(
        f"[green]Etapa {step.position} adicionada:[/green] {step.name}"
        f" [dim](abertura +{step.offset_days}d)[/dim]"
    )


@app.command("run")
def run(
    ref: str = typer.Argument(..., help="Número ou nome da rotina"),
    period: str = typer.Option(
        None, "--period", "-p", help="Período (YYYY-MM ou YYYY-Www); padrão: o atual"
    ),
):
    """Materializa um ciclo na mão (para adiantar ou recuperar um período)."""
    conn = db.connect()
    routine = _find(conn, ref)
    period = period or schedule.period_key(routine.cadence, date.fromisoformat(db.today()))
    try:
        ciclo = services.materialize_run(conn, routine, period)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    stages = db.list_stages(conn, ciclo.id)
    console.print(f"[green]Ciclo pronto:[/green] {ciclo.name} (prazo {ciclo.deadline})")
    console.print(f"[dim]{len(stages)} etapa(s).[/dim]")


@app.command("close")
def close(
    ref: str = typer.Argument(..., help="Número ou nome da rotina"),
    period: str = typer.Option(None, "--period", "-p", help="Período; padrão: o ciclo mais recente"),
    on: str = typer.Option(
        None, "--on", help="Data do fechamento (YYYY-MM-DD); padrão: agora"
    ),
):
    """Fecha um ciclo. É sempre manual — ver a janela aberta é o sinal que a rotina dá."""
    conn = db.connect()
    routine = _find(conn, ref)
    if period:
        ciclo = db.find_routine_run(conn, routine.id, period)
    else:
        runs = db.list_routine_runs(conn, routine.id, include_done=False)
        ciclo = runs[-1] if runs else None
    if ciclo is None:
        console.print(f"[red]Nenhum ciclo aberto em {routine.name}.[/red]")
        raise typer.Exit(1)
    pendentes = db.list_stages(conn, ciclo.id, include_done=False)
    if pendentes:
        nomes = ", ".join(s.name for s in pendentes)
        console.print(f"[yellow]Etapas ainda pendentes: {nomes}[/yellow]")
    try:
        ciclo = services.close_routine_run(conn, ciclo, closed_on=on)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    dentro = ciclo.deadline and ciclo.done_at[:10] <= ciclo.deadline
    sla = "[green]dentro do SLA[/green]" if dentro else "[yellow]fora do SLA[/yellow]"
    console.print(f"[green]✔ Ciclo fechado:[/green] {ciclo.name} em {ciclo.done_at[:10]} — {sla}")


@app.command("archive")
def archive(ref: str = typer.Argument(..., help="Número ou nome da rotina")):
    """Arquiva a rotina: para de abrir ciclos novos, o histórico continua."""
    conn = db.connect()
    routine = _find(conn, ref)
    db.archive_routine(conn, routine.id)
    console.print(f"[green]✔ Rotina arquivada:[/green] {routine.name}")
