"""Ponto de entrada da CLI `wa`."""

import typer

from work_assistant.commands import chat, checkpoint, plan, project, review, todo, web

app = typer.Typer(
    help="Assistente pessoal de trabalho com modelo local (llama.cpp).",
    no_args_is_help=True,
)

app.add_typer(todo.app, name="todo")
app.add_typer(project.app, name="project")
app.add_typer(plan.app, name="plan", help="Monta o to-do do dia com ajuda do modelo.")
app.add_typer(checkpoint.app, name="checkpoint", help="Check-in de progresso de um projeto.")
app.add_typer(review.app, name="review", help="Análise de execução: atrasos, tempos e tags.")
app.add_typer(chat.app, name="chat", help="Conversa livre com contexto das suas tarefas.")
app.add_typer(web.app, name="web", help="Abre a interface web local do assistente.")


if __name__ == "__main__":
    app()
