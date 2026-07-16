# CLAUDE.md

Assistente pessoal de trabalho com modelos locais via llama.cpp. CLI `wa` em Python (typer + rich), dados em SQLite, inferência via servidor llama.cpp em Docker (API OpenAI-compatible).

## Arquitetura

- `src/work_assistant/cli.py` — app typer raiz; registra os subcomandos.
- `src/work_assistant/db.py` — toda a persistência (SQLite em `~/.ai-work-assistant/assistant.db`). Schema: `tasks` (to-do diário, coluna `day`), `projects` (entregas com `goal`), `checkpoints` (relato + avaliação do modelo).
- `src/work_assistant/llm.py` — cliente do llama.cpp. `complete()` para texto; `structured()` para JSON garantido via `json_schema` (gramática GBNF do llama.cpp). `quality=True` roteia para o servidor do 9B (porta 8081).
- `src/work_assistant/config.py` — configuração via env vars `WA_*`; nada hardcoded nos comandos.
- `src/work_assistant/context.py` — monta os blocos de contexto (tarefas/projetos/checkpoints) injetados nos prompts.
- `src/work_assistant/prompts/*.md` — prompts em PT-BR, um por comando. Ajustes de comportamento do modelo acontecem AQUI, não no código.
- `src/work_assistant/commands/` — um módulo por comando. `todo` e `project` funcionam sem LLM; `plan`, `checkpoint`, `standup` e `chat` exigem o servidor de pé.
- `docker/docker-compose.yml` — servidor llama.cpp (Qwen3.5 4B, otimizado p/ RTX 3050 4GB) + profile `quality` (Qwen3.5 9B, porta 8081).

## Comandos de desenvolvimento

```bash
.venv/bin/pip install -e ".[dev]"   # setup (venv em .venv/, Python via asdf/.tool-versions)
.venv/bin/python -m pytest          # testes — NÃO dependem do modelo/Docker
.venv/bin/ruff check src tests scripts
docker compose -f docker/docker-compose.yml up -d   # servidor LLM (precisa de GPU no Docker/WSL)
```

## Convenções

- Idioma: código/identificadores em inglês; strings visíveis ao usuário, prompts, docs e mensagens de commit em PT-BR.
- Testes não podem chamar o LLM: teste `db.py` direto e os comandos via `typer.testing.CliRunner` (LLM mockado se necessário). Fixture padrão: monkeypatch em `config.DB_PATH` para `tmp_path`.
- Datas como strings ISO (`YYYY-MM-DD`) — o SQLite compara lexicograficamente.
- Novos comandos: criar módulo em `commands/`, registrar em `cli.py` com `app.add_typer`, prompt correspondente em `prompts/`.
- Hardware alvo: RTX 3050 Laptop 4GB VRAM. Qualquer mudança nas flags do docker-compose deve manter o uso de VRAM abaixo de ~3.5GB (validar com `nvidia-smi`).
- A escolha de modelo está documentada em `docs/model-evaluation.md` — atualizar se trocar o modelo padrão.
