"""Ponto de entrada da CLI `wa`."""

import typer

from work_assistant.commands import chat, checkpoint, plan, project, standup, todo

app = typer.Typer(
    help="Assistente pessoal de trabalho com modelo local (llama.cpp).",
    no_args_is_help=True,
)

app.add_typer(todo.app, name="todo")
app.add_typer(project.app, name="project")
app.add_typer(plan.app, name="plan", help="Monta o to-do do dia com ajuda do modelo.")
app.add_typer(checkpoint.app, name="checkpoint", help="Check-in de progresso de um projeto.")
app.add_typer(standup.app, name="standup", help="Gera a fala da daily a partir do histórico.")
app.add_typer(chat.app, name="chat", help="Conversa livre com contexto das suas tarefas.")


if __name__ == "__main__":
    app()
