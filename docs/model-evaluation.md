# Avaliação de modelos locais (julho/2026)

Escolha do modelo padrão do assistente. Hardware alvo: **RTX 3050 Laptop 4GB VRAM**, i7 13ª gen, 32GB RAM, WSL2 Ubuntu + Docker.

## Critérios

1. **Caber em 4GB de VRAM** em quantização Q4, com espaço para o KV cache — inferência 100% na GPU é o que garante velocidade interativa.
2. **Português do Brasil fluente** — todos os prompts e interações são em PT-BR.
3. **Tool calling / saída estruturada confiável** — o `wa plan` depende de JSON válido (mitigado pela gramática GBNF do llama.cpp, mas o modelo precisa preencher o schema com conteúdo bom).
4. **Licença permissiva** — o projeto é público.

## Comparativo

| Modelo | Peso Q4_K_M | VRAM efetiva | PT-BR | Instrução/agentic | Licença | Veredito |
|---|---|---|---|---|---|---|
| **Qwen3.5 4B Instruct** | 2.74 GB | ~3.3 GB c/ KV q8_0 → 100% GPU | Muito bom (100+ idiomas) | Forte; contexto 262K | Apache 2.0 | ✅ **Escolhido** |
| Gemma 3 4B / Gemma 4 small | ~2.7 GB | similar | Muito bom | Mais fraco em raciocínio multi-etapas e tool calling | Gemma (restrições) | Alternativa |
| Phi-4-mini 3.8B | ~2.5 GB | similar | Fraco | Ótimo em inglês | MIT | ❌ PT-BR insuficiente |
| Llama 3.2 3B | ~2.0 GB | folga | OK | Geração anterior, abaixo do Qwen3.5 4B em tudo | Llama license | ❌ Superado |
| Qwen3.5 9B Instruct | 5.68 GB | não cabe → offload parcial (`-ngl 24`) | Excelente | Forte | Apache 2.0 | ⚙️ **Modo qualidade** opcional |

## Decisão

**Padrão: `unsloth/Qwen3.5-4B-GGUF` → `Qwen3.5-4B-Q4_K_M.gguf`.**
Na RTX 3050 4GB roda inteiro na GPU com KV cache q8_0 e contexto de 8K (~3.3GB de VRAM), com expectativa de 25–40 tokens/s — velocidade confortável para `wa plan` e `wa chat`.

**Modo qualidade: `unsloth/Qwen3.5-9B-GGUF` → `Qwen3.5-9B-Q4_K_M.gguf`.**
Com 32GB de RAM, roda com offload parcial (18 camadas na GPU, resto na CPU — ver benchmarks abaixo). Lento demais para chat, mas adequado para o `wa standup`, que é geração única e curta. Ativado via profile `quality` do docker-compose + `WA_QUALITY_MODEL=qwen3.5-9b`.

## Flags do llama.cpp (RTX 3050 4GB)

| Flag | Efeito |
|---|---|
| `-ngl 99` | Todas as camadas na GPU (o 4B cabe) |
| `--flash-attn on` | Menos VRAM/mais rápido; pré-requisito do cache V quantizado |
| `--cache-type-k q8_0 --cache-type-v q8_0` | KV cache pela metade, perda desprezível |
| `-c 8192` | Contexto suficiente p/ os prompts do assistente sem estourar 4GB |
| `--jinja` | Chat template nativo do Qwen (tool calling/JSON) |

Validação na máquina alvo: `nvidia-smi` (processo < ~3.5GB) e `llama-bench` para tokens/s.

## Benchmarks medidos (2026-07-16, RTX 4070 12GB)

Matriz de configs medida com a imagem `server-cuda` oficial, prompt de ~700 tokens + geração de 256. A **VRAM é transferível para a 3050** (depende do modelo/flags, não da GPU); a velocidade escala para baixo pela banda de memória (4070 ~504 GB/s vs 3050 Laptop ~192 GB/s → fator ~0.4 na geração).

### Qwen3.5 4B (Q4_K_M, `-ngl 99`)

| Config | VRAM | Prompt (t/s) | Geração (t/s) |
|---|---|---|---|
| **flash-attn + KV q8_0, c=8192 (adotada)** | **3164 MiB** | 3216 | 115 |
| flash-attn + KV f16, c=8192 | 3258 MiB | 3515 | 119 |
| flash-attn + KV q4_0, c=8192 | 3077 MiB | 3545 | 117 |
| flash-attn + KV q8_0, c=16384 | 3405 MiB | 3288 | 117 |
| flash-attn + KV q8_0, c=4096 | 3120 MiB | 3047 | 114 |
| sem flash-attn, KV f16, c=8192 | 3566 MiB | 1780 | 115 |

Conclusões:
- **flash-attn é obrigatório**: sem ele o prompt processing cai pela metade e a VRAM sobe 400 MiB.
- O KV quantizado economiza pouco neste modelo (GQA agressivo), mas custa quase nada — mantido q8_0 pela margem de segurança na 3050.
- Todas as variantes com flash-attn cabem nos 4096 MiB da 3050. **Estimativa na 3050: ~40–45 t/s de geração, ~1200 t/s de prompt** — confortável para uso interativo.

### Qwen3.5 9B (Q4_K_M, offload parcial, flash-attn + KV q8_0, c=8192)

| `-ngl` | VRAM | Prompt (t/s) | Geração (t/s) | Cabe na 3050 (4096 MiB)? |
|---|---|---|---|---|
| 28 | 4517 MiB | 1164 | 26.2 | ❌ |
| 24 | 4280 MiB | 994 | 16.9 | ❌ |
| 20 | 3770 MiB | 831 | 13.3 | ⚠️ margem de ~330 MiB |
| **18 (adotada)** | **3490 MiB** | 730 | 11.0 | ✅ margem de ~600 MiB |
| 16 | 2812 MiB | 626 | 10.5 | ✅ folga grande |

Conclusões:
- O valor original (`-ngl 24`) **estourava a VRAM da 3050** — corrigido para 18.
- Na 3050 a parte GPU será mais lenta e a geração depende também da CPU (i7 13ª gen): estimativa **~6–9 t/s**. OK para o `wa standup`; inviável para chat.
- Se na máquina alvo o `nvidia-smi` mostrar folga (> 600 MiB livres), vale testar `-ngl 20`.

## Fontes

- [Best Local AI Models by VRAM Tier 2026](https://runaihome.com/blog/best-local-ai-models-by-vram/)
- [Running Local LLMs on a 6GB GPU Laptop in 2026](https://medium.com/@kundansinghsorout/running-local-llms-on-a-6gb-gpu-laptop-what-actually-works-in-2026-and-what-doesnt-487fda2a604e)
- [Best Local LLMs for Function Calling](https://insiderllm.com/guides/function-calling-local-llms/)
- [Gemma 4 vs Qwen 3.5: Open LLM Comparison](https://codersera.com/blog/gemma-4-vs-qwen-3-5-comparison-2026/)
- [Best Small Language Models 2026](https://localaimaster.com/blog/small-language-models-guide-2026)
- [9 Modelos de Linguagem com Melhor Custo-Benefício para Rodar Localmente](https://elisaterumi.substack.com/p/9-modelos-de-linguagem-com-melhor)
