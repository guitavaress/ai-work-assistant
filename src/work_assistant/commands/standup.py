"""`wa standup` — gera a fala da daily a partir do histórico."""

from datetime import date, timedelta

import typer
from rich.console import Console
from rich.markdown import Markdown

from work_assistant import context, db, llm

app = typer.Typer()
console = Console()


@app.callback(invoke_without_command=True)
def standup(
    days: int = typer.Option(1, "--days", "-n", help="Quantos dias para trás olhar (padrão: 1)"),
):
    """Resume o que foi feito e o que vem hoje, no formato de daily/standup."""
    conn = db.connect()
    start = (date.today() - timedelta(days=days)).isoformat()
    past_tasks = db.list_tasks_between(conn, start, date.today().isoformat())
    if not past_tasks:
        console.print("[yellow]Sem histórico no período — nada para resumir.[/yellow]")
        raise typer.Exit(1)

    lines = []
    for t in past_tasks:
        status = "feita" if t.status == "done" else "pendente"
        lines.append(f"- {t.day} [{status}] {t.title}")

    user_message = (
        f"Hoje é {db.today()}.\n\n"
        f"Histórico de tarefas ({start} a hoje):\n" + "\n".join(lines) + "\n\n"
        f"Projetos ativos:\n{context.projects_block(conn)}"
    )
    with console.status("Preparando o standup..."):
        summary = llm.complete(llm.load_prompt("standup"), user_message, quality=True)
    console.print(Markdown(summary))
