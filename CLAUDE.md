# CLAUDE.md

Assistente pessoal de trabalho com modelos locais via llama.cpp. CLI `wa` em Python (typer + rich), dados em SQLite, inferência via servidor llama.cpp em Docker (API OpenAI-compatible).

## Arquitetura

- `src/work_assistant/cli.py` — app typer raiz; registra os subcomandos.
- `src/work_assistant/db.py` — toda a persistência (SQLite em `~/.ai-work-assistant/assistant.db`). Schema: `tasks` (to-do diário, coluna `day`; `due_date`/`tags`/`effort` P|M|G/`source` manual|plan; `project_id` opcional para vincular a task a um projeto — atribuição sempre manual via `--project`/`wa todo project`), `projects` (entregas com `goal` e `deadline`), `checkpoints` (relato + avaliação do modelo + `status`/`summary` para a web). Colunas novas entram via `_MIGRATIONS` (ALTER TABLE no `connect()`).
- `src/work_assistant/services.py` — lógica de negócio compartilhada (plan/checkpoint/chat/review): monta contexto, chama o modelo e persiste. CLI e web SEMPRE passam por aqui — nada de montagem de prompt nos comandos ou na API. `review_metrics()` calcula as métricas de execução (atrasos, lead time, % não planejado, por tag/esforço) sem LLM; `run_review()` soma a avaliação do modelo (único caminho que usa `quality=True`).
- `src/work_assistant/llm.py` — cliente do llama.cpp. `complete()` para texto; `structured()` para JSON garantido via `json_schema` (gramática GBNF do llama.cpp). `quality=True` roteia para o servidor do 9B (porta 8081) com thinking ligado (`QUALITY_ENABLE_THINKING`) e teto de tokens maior; `structured()` roda sempre sem thinking.
- `src/work_assistant/config.py` — configuração via env vars `WA_*`; nada hardcoded nos comandos.
- `src/work_assistant/context.py` — monta os blocos de contexto (tarefas/projetos/checkpoints) injetados nos prompts.
- `src/work_assistant/prompts/*.md` — prompts em PT-BR, um por comando. Ajustes de comportamento do modelo acontecem AQUI, não no código.
- `src/work_assistant/commands/` — um módulo por comando. `todo` e `project` funcionam sem LLM; `plan`, `checkpoint`, `chat` e `review` exigem o servidor de pé (o `review` só para a avaliação — as métricas são locais).
- `src/work_assistant/web/` — interface web (`wa web`): `api.py` (FastAPI, camada fina sobre `services.py`/`db.py`) + `static/index.html` (frontend vanilla JS em arquivo único, sem build). Layout "cockpit" (duas colunas, 1160px): Hoje com to-do + sidebar (projetos com barra de progresso, ritual do dia) e day-nav no topo; clicar numa tarefa abre popover de edição (projeto/tags/prazo/esforço) via `POST /api/tasks/{id}`. O design de referência é o `WA App Cockpit.dc.html` no projeto Claude Design "Interface visual para projeto" (protótipo declarativo `.dc.html`, não executável).
- `docker/docker-compose.yml` — servidor llama.cpp (Qwen3.5 4B, otimizado p/ RTX 3050 6GB) + profile `quality` (Qwen3.5 9B IQ4_XS inteiro na GPU, porta 8081). Os dois não cabem residentes ao mesmo tempo nos 6GB — use um profile por vez.

## Comandos de desenvolvimento

```bash
.venv/bin/pip install -e ".[dev]"   # setup (venv em .venv/, Python via asdf/.tool-versions)
.venv/bin/python -m pytest          # testes — NÃO dependem do modelo/Docker
.venv/bin/ruff check src tests scripts
docker compose -f docker/docker-compose.yml up -d   # servidor LLM (precisa de GPU no Docker/WSL)
```

## Convenções

- Idioma: código/identificadores em inglês; strings visíveis ao usuário, prompts, docs e mensagens de commit em PT-BR.
- Testes não podem chamar o LLM: teste `db.py` direto, os comandos via `typer.testing.CliRunner` e a API web via `fastapi.testclient.TestClient` (LLM mockado com monkeypatch em `llm.structured`/`llm.complete`). Fixture padrão: monkeypatch em `config.DB_PATH` para `tmp_path`.
- Datas como strings ISO (`YYYY-MM-DD`) — o SQLite compara lexicograficamente.
- Novos comandos: criar módulo em `commands/`, registrar em `cli.py` com `app.add_typer`, prompt correspondente em `prompts/`.
- Hardware alvo: RTX 3050 Laptop 6GB VRAM. Qualquer mudança nas flags do docker-compose deve manter o uso de VRAM abaixo de ~5.7GB (o 4B padrão fica em ~3.2GB; o 9B em modo qualidade opera perto do limite, ~5.8GB — validar sempre com `nvidia-smi` na 3050).
- A escolha de modelo está documentada em `docs/model-evaluation.md` — atualizar se trocar o modelo padrão.
