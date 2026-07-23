"""`wa review` — análise de execução das tarefas do período."""

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from work_assistant import db, services

app = typer.Typer()
console = Console()


def _pct(rate: float | None) -> str:
    return f"{rate:.0%}" if rate is not None else "-"


def _days_(value: float | None) -> str:
    return f"{value} d" if value is not None else "-"


def _render_metrics(m: dict) -> None:
    period = m["period"]
    table = Table(title=f"Execução de {period['start']} a {period['end']}")
    table.add_column("Métrica")
    table.add_column("Valor", justify="right")
    table.add_row("Tarefas no período", str(m["total"]))
    table.add_row("Concluídas / pendentes", f"{m['done']} / {m['pending']}")
    table.add_row("Atrasadas agora", str(len(m["overdue"])))
    table.add_row("Entrega no prazo", _pct(m["on_time_rate"]))
    table.add_row("Viraram o dia (carryover)", _pct(m["carryover_rate"]))
    table.add_row("Trabalho não planejado", _pct(m["unplanned_rate"]))
    table.add_row("Lead time médio", _days_(m["avg_lead_days"]))
    table.add_row("Throughput", f"{m['throughput_per_week']} tarefas/semana")
    console.print(table)

    if m["overdue"]:
        late = Table(title="Tarefas atrasadas")
        late.add_column("#", justify="right")
        late.add_column("Tarefa")
        late.add_column("Prazo")
        for t in m["overdue"]:
            late.add_row(str(t["id"]), t["title"], f"[red]{t['due']}[/red]")
        console.print(late)

    if m["by_effort"]:
        eff = Table(title="Por esforço estimado")
        eff.add_column("Esf", justify="center")
        eff.add_column("Tarefas", justify="right")
        eff.add_column("Concluídas", justify="right")
        eff.add_column("Lead médio", justify="right")
        for level, s in m["by_effort"].items():
            eff.add_row(level, str(s["total"]), str(s["done"]), _days_(s["avg_lead_days"]))
        console.print(eff)

    if m["by_tag"]:
        tags = Table(title="Por tag")
        tags.add_column("Tag")
        tags.add_column("Tarefas", justify="right")
        tags.add_column("Concluídas", justify="right")
        tags.add_column("Atrasadas", justify="right")
        tags.add_column("Lead médio", justify="right")
        for tag, s in m["by_tag"].items():
            tags.add_row(
                tag, str(s["total"]), str(s["done"]), str(s["overdue"]), _days_(s["avg_lead_days"])
            )
        console.print(tags)


@app.callback(invoke_without_command=True)
def review(
    days: int = typer.Option(14, "--days", "-n", help="Janela de análise em dias (padrão: 14)"),
):
    """Mostra métricas de execução do período e a avaliação do modelo."""
    conn = db.connect()
    try:
        with console.status("Analisando o período..."):
            result = services.run_review(conn, days)
    except LookupError as e:
        console.print(f"[yellow]{e}[/yellow]")
        raise typer.Exit(1)
    _render_metrics(result["metrics"])
    console.print(Panel(Markdown(result["assessment"]), title="Avaliação do modelo"))
