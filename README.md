# AI Work Assistant

Assistente pessoal de trabalho rodando **100% local** com [llama.cpp](https://github.com/ggml-org/llama.cpp) — nenhum dado sai da sua máquina. Feito para melhorar organização diária e qualidade de entregas:

- **`wa plan`** — transforma seu relato do dia em um to-do priorizado (com ajuda do modelo).
- **`wa todo`** — adiciona, lista e conclui tarefas do dia.
- **`wa checkpoint`** — check-in de sprint: você relata o progresso de um projeto e o modelo avalia contra o objetivo da entrega, apontando riscos e próximos passos.
- **`wa review`** — análise de execução do período: atrasos, lead time, trabalho não planejado e avaliação do modelo.
- **`wa chat`** — conversa livre com o contexto das suas tarefas e projetos.

Otimizado para rodar em notebook com GPU modesta (referência: **RTX 3050 Laptop 6GB** + 32GB RAM) em **Windows + WSL2 Ubuntu** com Docker.

## Arquitetura

```
┌─────────────────────────── WSL2 Ubuntu ───────────────────────────┐
│                                                                   │
│  wa (CLI Python, pipx)  ──HTTP──▶  llama.cpp server (Docker CUDA) │
│         │                              │                          │
│   ~/.ai-work-assistant/assistant.db    │ GPU passthrough WSL2     │
│   ~/.ai-work-assistant/models/*.gguf ◀─┘                          │
└───────────────────────────────────────────────────────────────────┘
```

- O **servidor de inferência** roda em Docker (imagem oficial CUDA do llama.cpp) e expõe uma API OpenAI-compatible em `http://localhost:8080/v1`.
- A **CLI** roda nativa no Ubuntu e guarda seus dados em SQLite (`~/.ai-work-assistant/`).
- Modelo padrão: **Qwen3.5 4B Instruct (Q4_K_M)** — ver [avaliação de modelos](docs/model-evaluation.md).

## Requisitos

- Windows 11 com WSL2 + Ubuntu e driver NVIDIA atualizado **no Windows** (não instale driver dentro do Ubuntu).
- Docker com acesso à GPU dentro do WSL, por um dos caminhos:
  - **Docker Desktop**: Settings → Resources → WSL Integration → habilitar no seu distro Ubuntu; ou
  - **Docker Engine direto no Ubuntu** + [nvidia-container-toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).
- Python 3.10+ e [pipx](https://pipx.pypa.io/) no Ubuntu.

Valide a GPU no Docker antes de seguir:

```bash
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

## Instalação

```bash
git clone https://github.com/<seu-usuario>/ai-work-assistant.git
cd ai-work-assistant

# 1. Baixa o modelo (Qwen3.5 4B Q4_K_M, ~2.6GB) para ~/.ai-work-assistant/models/
python3 scripts/download_model.py

# 2. Sobe o servidor llama.cpp (fica rodando em segundo plano)
docker compose -f docker/docker-compose.yml up -d

# 3. Instala a CLI
pipx install .
```

Teste: `wa todo add "Primeira tarefa"` e depois `wa todo list`.

## Uso no dia a dia

```bash
wa plan                          # de manhã: monta o to-do do dia com o modelo
wa todo done 3                   # ao longo do dia: conclui tarefas
wa project add "API v2" -g "Publicar API v2 com autenticação até a sprint 14"
wa checkpoint "API v2"           # 1–2x por semana: check-in de progresso
wa review                        # a cada sprint: análise de atrasos, tempos e trabalho não planejado
```

## Interface web

Além da CLI, o assistente tem uma interface web local — mesmos dados (SQLite) e mesmo servidor de modelo:

```bash
wa web            # sobe em http://127.0.0.1:8765 e abre o navegador
wa web --no-browser
```

- **Hoje** — saudação, to-do do dia (adicionar e concluir com um clique) e o botão "Planejar o dia", que transforma seu relato em um to-do priorizado pelo modelo.
- **Projetos** — cards com objetivo, tag de situação (`no rumo` / `em risco`) derivada do último checkpoint e timeline de check-ins.
- **Chat** — conversa com o contexto das suas tarefas e projetos.
- **Histórico** — navegação pelos to-dos de dias anteriores.
- Checkpoint abre em modal com a avaliação em blocos (Situação/Riscos/Próximo passo), com botão de copiar.
- Tema claro/escuro (persistido no navegador) e indicador de status do servidor llama.cpp no topo — ações de modelo avisam quando o servidor está fora do ar.

## Otimização para RTX 3050 6GB

O `docker-compose.yml` já vem com as flags ajustadas para caber com folga nos 6GB (o 4B padrão usa ~3.2GB):

| Flag | Por quê |
|---|---|
| `-ngl 99` | Todas as camadas do 4B Q4_K_M cabem na GPU (~2.6GB) |
| `--flash-attn on` | Menos VRAM e mais velocidade; requisito para quantizar o cache V |
| `--cache-type-k q8_0 --cache-type-v q8_0` | KV cache na metade do tamanho, perda de qualidade desprezível |
| `-c 8192` | Contexto suficiente para os prompts do assistente sem estourar VRAM |
| `--jinja` | Habilita o chat template do Qwen (tool calling / saída estruturada) |

Monitore com `nvidia-smi` na primeira execução: medido em **3164 MiB** de VRAM (RTX 4070; o valor transfere para a 3050). Expectativa na RTX 3050: **~40 tokens/s** de geração. Benchmarks completos da matriz de configs em [docs/model-evaluation.md](docs/model-evaluation.md).

### Modo qualidade (opcional)

Nos 6GB dá para rodar o **Qwen3.5 9B** (quant IQ4_XS) **inteiro na GPU** (`-ngl 99`) — raciocínio bem melhor que o 4B, com thinking ligado. Medido em **~5.0GB de VRAM** (cabe nos 6GB com ~1.1GB de folga) e **~80 t/s** de geração na 4070 (estimado ~30 t/s na 3050) — muito acima do offload parcial anterior. O `wa review` usa este modelo quando ativado. Baixe com `python3 scripts/download_model.py --quality`, suba com `docker compose -f docker/docker-compose.yml --profile quality up -d` e aponte o assistente para ele:

```bash
export WA_QUALITY_MODEL=qwen3.5-9b
```

> O 4B (padrão) e o 9B (qualidade) **não cabem juntos** nos 6GB — suba um profile por vez.

## Configuração

Variáveis de ambiente (todas opcionais):

| Variável | Padrão | Descrição |
|---|---|---|
| `WA_DATA_DIR` | `~/.ai-work-assistant` | Onde ficam o SQLite e os modelos |
| `WA_LLM_BASE_URL` | `http://localhost:8080/v1` | Endpoint do servidor llama.cpp |
| `WA_LLM_MODEL` | `qwen3.5-4b` | Nome do modelo padrão |
| `WA_QUALITY_MODEL` | *(vazio)* | Modelo usado pelo `wa review`, se definido |
| `WA_QUALITY_BASE_URL` | `http://localhost:8081/v1` | Endpoint do servidor do modo qualidade |
| `WA_LLM_TIMEOUT` | `120` | Timeout das chamadas ao modelo (s) |
| `WA_ENABLE_THINKING` | *(desligado)* | `1` ativa o modo thinking do Qwen nas respostas de texto do modelo padrão (mais qualidade, bem mais lento) |
| `WA_QUALITY_ENABLE_THINKING` | `1` (ligado) | Thinking no caminho de qualidade (9B); `0` desliga. Só afeta texto livre — a saída estruturada nunca usa thinking |
| `WA_MAX_TOKENS` | `2048` | Limite de tokens por resposta |
| `WA_QUALITY_MAX_TOKENS` | `4096` | Limite de tokens no caminho de qualidade (espaço para o thinking + resposta) |
| `WA_WEB_HOST` | `127.0.0.1` | Host da interface web (`wa web`) |
| `WA_WEB_PORT` | `8765` | Porta da interface web |
| `WA_USER_NAME` | *(vazio)* | Nome usado na saudação da interface web |

## Desenvolvimento

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest        # testes (não precisam do modelo)
.venv/bin/ruff check src tests    # lint
```

## Licença

[MIT](LICENSE)
