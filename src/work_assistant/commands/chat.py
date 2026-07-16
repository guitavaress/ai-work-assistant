"""`wa chat` — conversa livre com o contexto das tarefas e projetos."""

import typer
from rich.console import Console
from rich.markdown import Markdown

from work_assistant import context, db, llm

app = typer.Typer()
console = Console()


@app.callback(invoke_without_command=True)
def chat():
    """Conversa com o assistente (Ctrl+D ou 'sair' para encerrar)."""
    conn = db.connect()
    system = (
        llm.load_prompt("chat")
        + f"\n\nTarefas de hoje:\n{context.tasks_block(conn)}"
        + f"\n\nProjetos ativos:\n{context.projects_block(conn)}"
    )
    console.print("[dim]Chat iniciado. Ctrl+D ou 'sair' para encerrar.[/dim]\n")
    history: list[dict] = []
    while True:
        try:
            user_input = console.input("[bold cyan]você>[/bold cyan] ").strip()
        except EOFError:
            break
        if not user_input:
            continue
        if user_input.lower() in {"sair", "exit", "quit"}:
            break
        with console.status("Pensando..."):
            reply = llm.complete(system, user_input, history=history)
        history.append({"role": "user", "content": user_input})
        history.append({"role": "assistant", "content": reply})
        console.print(Markdown(reply))
        console.print()
    console.print("[dim]Até mais![/dim]")
    raise typer.Exit()
