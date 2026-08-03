# CLAUDE.md

Assistente pessoal de trabalho com modelos locais via llama.cpp. CLI `wa` em Python (typer + rich), dados em SQLite, inferência via servidor llama.cpp em Docker (API OpenAI-compatible).

## Arquitetura

- `src/work_assistant/cli.py` — app typer raiz; registra os subcomandos.
- `src/work_assistant/db.py` — toda a persistência (SQLite em `~/.ai-work-assistant/assistant.db`). Schema: `tasks` (to-do diário, coluna `day`; `due_date`/`tags`/`effort` P|M|G/`source` manual|plan; `project_id` e `stage_id` opcionais — atribuição sempre manual via `--project`/`--stage`/`wa todo project|stage`), `projects` (entregas com `goal` e `deadline`), `stages` (etapas do projeto: `position`, `deadline`, `done_criteria`), `routines` + `routine_steps` (molde do trabalho recorrente), `checkpoints` (relato + avaliação do modelo + `status`/`summary` para a web + `stage_id` opcional). Colunas novas entram via `_MIGRATIONS` (ALTER TABLE no `connect()`); **índices vão na constante `INDEXES`, nunca no `SCHEMA`** — o `SCHEMA` roda antes do `_migrate()` e um índice sobre coluna nova quebraria todo banco existente. Progresso de projeto/etapa tem função canônica (`project_progress`/`stage_progress`) — não recontar tarefas na mão.
- `src/work_assistant/schedule.py` — aritmética de cadência e janela das rotinas. Períodos: `YYYY-MM-DD` (diária, seg–sex), `YYYY-Www` (semanal ISO), `YYYY-MM` (mensal), `YYYY-Tn` (trimestral). **`sla_days` é a DURAÇÃO da janela contando o dia de abertura** (abre dia 1 com `sla_days=5` e fecha dia 5) — não é deslocamento. Módulo **puro**: sem banco e sem imports do pacote, e nada aqui chama `date.today()` — quem precisa de "hoje" recebe por parâmetro, o que mantém os testes determinísticos.
- `src/work_assistant/services.py` — lógica de negócio compartilhada (plan/checkpoint/chat/review/rotinas): monta contexto, chama o modelo e persiste. CLI e web SEMPRE passam por aqui — nada de montagem de prompt nos comandos ou na API. `review_metrics()` calcula as métricas de execução (atrasos, lead time, % não planejado, por tag/esforço) sem LLM; `run_review()` soma a avaliação do modelo (único caminho que usa `quality=True`). `ensure_routines()` materializa os ciclos cuja janela abriu — chamada logo após o `db.connect()` em todo comando que lê o dia (`todo list`, `plan`, `project list`, `routine`, `GET /api/state`); nunca dentro do `connect()`.
- `src/work_assistant/llm.py` — cliente do llama.cpp. `complete()` para texto; `structured()` para JSON garantido via `json_schema` (gramática GBNF do llama.cpp). `quality=True` roteia para o servidor do 9B (porta 8091) com thinking ligado (`QUALITY_ENABLE_THINKING`) e teto de tokens maior; `structured()` roda sempre sem thinking.
- `src/work_assistant/config.py` — configuração via env vars `WA_*`; nada hardcoded nos comandos.
- `src/work_assistant/context.py` — monta os blocos de contexto (tarefas/projetos/etapas/rotinas/checkpoints) injetados nos prompts.
- `src/work_assistant/prompts/*.md` — prompts em PT-BR, um por comando. Ajustes de comportamento do modelo acontecem AQUI, não no código.
- `src/work_assistant/commands/` — um módulo por comando. `todo`, `project` e `routine` funcionam sem LLM; `plan`, `checkpoint`, `chat` e `review` exigem o servidor de pé (o `review` só para a avaliação — as métricas são locais).
- `src/work_assistant/web/` — interface web (`wa web`): `api.py` (FastAPI, camada fina sobre `services.py`/`db.py`) + `static/index.html` (frontend vanilla JS em arquivo único, sem build). Layout "cockpit" (duas colunas, 1160px): Hoje com to-do + sidebar (projetos com barra de progresso, ritual do dia) e day-nav no topo; clicar numa tarefa abre popover de edição (projeto/tags/prazo/esforço) via `POST /api/tasks/{id}`. O design de referência é o `WA App Cockpit.dc.html` no projeto Claude Design "Interface visual para projeto" (protótipo declarativo `.dc.html`, não executável).
- `docker/docker-compose.yml` — servidor llama.cpp (Qwen3.5 4B, otimizado p/ RTX 3050 6GB) + profile `quality` (Qwen3.5 9B IQ4_XS inteiro na GPU, porta 8091). Os dois não cabem residentes ao mesmo tempo nos 6GB — use um profile por vez.

## Comandos de desenvolvimento

```bash
.venv/bin/pip install -e ".[dev]"   # setup (venv em .venv/, Python via asdf/.tool-versions)
.venv/bin/python -m pytest          # testes — NÃO dependem do modelo/Docker
.venv/bin/ruff check src tests scripts
docker compose -f docker/docker-compose.yml up -d   # servidor LLM (precisa de GPU no Docker/WSL)
```

## Projetos vs. Rotinas (run vs. change)

O app modela dois tipos de trabalho, e confundi-los é o erro mais fácil de cometer aqui:

- **Projeto** — entrega finita ("change"). Tem objetivo, prazo e acaba. `projects` com `kind='project'`.
- **Rotina** — trabalho recorrente ("run"): fechamento mensal, janela de comissões. Nunca termina — fecha um ciclo e volta. `routines` guarda só o **molde** (cadência, âncora de abertura, `sla_days`, checklist em `routine_steps`).
- **Ciclo** (`routine_run`) — a instância da rotina num período. É uma linha de `projects` com `kind='routine_run'` + `routine_id` + `period`, o que faz etapas, tarefas, checkpoints, progresso e métricas funcionarem sem código duplicado. As etapas do ciclo são **cópia** do checklist, não referência: editar a rotina não reescreve ciclos passados.

Regras que caem em armadilha se ignoradas:

- **Listar projeto ≠ listar ciclo.** `db.list_projects()` filtra `kind='project'` por padrão. Use `kind=None` em qualquer lugar que monte **mapa de nomes** (`context.py`, `_project_map` da API, `todo list`, `review_metrics`) — senão a tarefa de um ciclo aparece sem projeto. Falha em modo seguro: esquecer esconde, nunca vaza.
- O `<select>` do popover de edição da web precisa de `S.projects.concat(S.routine_runs)`. Sem os ciclos, uma tarefa de ciclo abre sem a própria opção, o browser seleciona `— sem projeto —` e o save **apaga o vínculo em silêncio**. Por isso `/api/state` devolve `routine_runs` numa chave separada.
- Fechar ciclo é sempre manual (`wa routine close`): ver a janela do mês passado ainda aberta é o sinal que a rotina existe para dar.
- Cadência usa dias de calendário, sem dia útil (exigiria calendário de feriados e testes dependentes dele). A única regra de dia da semana é a cadência diária, que pula sábado e domingo. Ampliação futura: coluna aditiva `sla_mode`.
- Rotina se cria pela CLI (`wa routine add` + `wa routine steps` no `$EDITOR`) **ou** pela web (formulário da aba Rotinas, `POST /api/routines` com o checklist inteiro). Criar rotina não materializa ciclo — ele nasce quando a janela abre; `wa routine run` e o botão "abrir ciclo agora" são a válvula para janela já passada.

## Convenções

- Idioma: código/identificadores em inglês; strings visíveis ao usuário, prompts, docs e mensagens de commit em PT-BR.
- Testes não podem chamar o LLM: teste `db.py` direto, os comandos via `typer.testing.CliRunner` e a API web via `fastapi.testclient.TestClient` (LLM mockado com monkeypatch em `llm.structured`/`llm.complete`). Fixture padrão: monkeypatch em `config.DB_PATH` para `tmp_path`.
- Datas como strings ISO (`YYYY-MM-DD`) — o SQLite compara lexicograficamente.
- Migração que **cria coluna** vai em `_MIGRATIONS` (keyed por `PRAGMA table_info`). Migração que **transforma dado** vai em `_migrate_data`, contada pelo `PRAGMA user_version` (`SCHEMA_VERSION` em `db.py`) — no `_MIGRATIONS` ela rodaria a cada `connect()`. Atenção: o pragma é global do arquivo `.db`, compartilhado com outras branches.
- Rótulo em PT-BR de janela/cadência/período mora em `schedule.py` e é servido ao front por `GET /api/routines/preview` — não reimplementar em JS, senão a web e a CLI passam a dizer frases diferentes para a mesma rotina.
- Novos comandos: criar módulo em `commands/`, registrar em `cli.py` com `app.add_typer`, prompt correspondente em `prompts/`. Exceção: comando **sem subcomandos e com argumento posicional** (ex.: `wa checkpoint <projeto> --stage`) precisa ser registrado com `app.command(...)` — via `add_typer` o Typer cria um Click Group, que trata o que vem depois do posicional como nome de subcomando e recusa as opções.
- Tarefa ↔ etapa tem invariante: definir a etapa define o projeto junto (a etapa manda); mover a tarefa de projeto solta a etapa se ela era de outro. Está em `db.set_task_stage`/`set_task_project` — não replicar essa lógica nos comandos.
- Hardware alvo: RTX 3050 Laptop 6GB VRAM. Qualquer mudança nas flags do docker-compose deve manter o uso de VRAM abaixo de ~5.7GB (o 4B padrão fica em ~3.2GB; o 9B em modo qualidade foi medido em ~5.0GB, cabe com folga — validar sempre com `nvidia-smi` na 3050).
- A escolha de modelo está documentada em `docs/model-evaluation.md` — atualizar se trocar o modelo padrão.
