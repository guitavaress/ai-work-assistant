"""`wa web` — sobe a interface web local do assistente."""

import threading
import webbrowser

import typer
import uvicorn
from rich.console import Console

from work_assistant import config

app = typer.Typer()
console = Console()


@app.callback(invoke_without_command=True)
def web(
    no_browser: bool = typer.Option(False, "--no-browser", help="Não abre o navegador automaticamente."),
):
    """Serve a interface web em http://WA_WEB_HOST:WA_WEB_PORT (Ctrl+C para parar)."""
    url = f"http://{config.WEB_HOST}:{config.WEB_PORT}"
    console.print(f"Interface web em [bold]{url}[/bold] (Ctrl+C para parar)")
    if not no_browser:
        threading.Timer(0.8, webbrowser.open, args=[url]).start()
    uvicorn.run(
        "work_assistant.web.api:app",
        host=config.WEB_HOST,
        port=config.WEB_PORT,
        log_level="warning",
    )
