"""`wa plan` — monta o to-do do dia com ajuda do modelo."""

import typer
from rich.console import Console

from work_assistant import context, db, llm
from work_assistant.commands.todo import render_tasks

app = typer.Typer()
console = Console()

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "priority": {"type": "integer"},
                },
                "required": ["title", "priority"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["tasks"],
    "additionalProperties": False,
}


@app.callback(invoke_without_command=True)
def plan():
    """Conversa curta que transforma seu relato do dia em um to-do priorizado."""
    conn = db.connect()
    relato = typer.prompt("O que você tem para hoje? (reuniões, entregas, pendências)")

    user_message = (
        f"Tarefas já pendentes hoje:\n{context.tasks_block(conn)}\n\n"
        f"Projetos ativos:\n{context.projects_block(conn)}\n\n"
        f"Relato do usuário:\n{relato}"
    )
    with console.status("Planejando o dia..."):
        result = llm.structured(llm.load_prompt("plan"), user_message, PLAN_SCHEMA)

    suggested = result.get("tasks", [])
    if not suggested:
        console.print("[yellow]O modelo não sugeriu tarefas. Tente detalhar mais o relato.[/yellow]")
        raise typer.Exit(1)

    console.print("\n[bold]Sugestão de to-do:[/bold]")
    for t in sorted(suggested, key=lambda t: t["priority"]):
        console.print(f"  {t['priority']}. {t['title']}")

    if not typer.confirm("\nSalvar essas tarefas no to-do de hoje?", default=True):
        console.print("[dim]Nada salvo.[/dim]")
        raise typer.Exit()

    for t in suggested:
        db.add_task(conn, t["title"], priority=t["priority"])
    render_tasks(db.list_tasks(conn), f"To-do de {db.today()}")
