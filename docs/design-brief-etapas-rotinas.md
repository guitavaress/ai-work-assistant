# Briefing de design — Etapas e Rotinas no cockpit

Documento para levar à conversa de Design (projeto Claude Design "Interface visual para
projeto", onde vive o protótipo `WA App Cockpit.dc.html`). Escrito para ser colado inteiro:
a conversa de Design não tem acesso ao repositório.

Estado do código: branch `main`, commits `13c4d9e` (etapas + rotinas) e `baf3ac1` (portas).

---

## 1. O que mudou no produto

O app modelava **um** tipo de trabalho: projeto — entrega finita, com objetivo e prazo,
acompanhada por checkpoints. Ao tentar cadastrar "Janela de Comissões" (fechamento de
comissões que roda todo início de mês) ficou claro que faltavam duas coisas.

**Etapa (`stage`).** Entregável intermediário dentro de um projeto, com prazo próprio,
ordem e — o que mais importa — um **critério de pronto** (`done_criteria`): uma frase
verificável como *"diferença < 0,01% contra o extrato do banco"*. Em engenharia de dados,
uma etapa não termina porque o código ficou pronto; termina quando o número bate. O
checkpoint agora julga cada etapa contra esse critério em vez de opinar sobre a impressão
que o relato passa.

**Rotina (`routine`) e ciclo (`routine_run`).** É a divisão clássica de operação de dados,
*run* vs *change*:

| | Projeto (change) | Rotina (run) |
|---|---|---|
| Termina? | Sim — entregou, acabou | Nunca. Fecha um ciclo e volta |
| Sucesso é | Entregar o escopo | Fechar a janela **dentro do SLA** |
| Prazo | Uma data-alvo | Uma **janela** que se repete (dias 1–5 do mês) |
| Aprendizado | Uma vez só | **Comparável a cada ciclo** |

A **rotina** é o molde (cadência, dia de abertura, SLA em dias, checklist de etapas). O
**ciclo** é a instância de um período — "Janela de Comissões — 2026-08" — materializada
sozinha quando a janela abre. Internamente o ciclo é uma linha da mesma tabela de projetos
(`kind='routine_run'`), então herda etapas, tarefas, checkpoints e progresso.

**A distinção precisa ficar visível na interface.** Se projeto e ciclo tiverem o mesmo
tratamento visual, o usuário recai exatamente na confusão que originou este trabalho. Na
CLI resolvi provisoriamente com um prefixo `⟳`; na tela isso merece coisa melhor.

## 2. Onde as coisas estão no repositório

```
src/work_assistant/
├── web/
│   ├── api.py                 FastAPI, camada fina. GET /api/state serve a tela inteira
│   └── static/index.html      frontend inteiro: 1022 linhas, vanilla JS, sem build
├── db.py                      schema e persistência
├── services.py                regra de negócio (materialização de ciclos, checkpoint)
└── schedule.py                aritmética de cadência/janela
docs/design-brief-etapas-rotinas.md   este documento
```

O frontend é **um arquivo único sem build**: HTML + CSS + JS vanilla no `index.html`, servido
direto pelo FastAPI. Não há React, bundler, nem npm. Qualquer proposta precisa caber nisso.

## 3. O que a interface tem hoje

Layout "cockpit", duas colunas, largura máxima 1160px. Nav: `Hoje | Projetos | Análise |
Chat | Histórico`. Tema claro/escuro via variáveis CSS, persistido no navegador.

- **Hoje** (`renderHoje()`, linha 473) — to-do do dia à esquerda; sidebar à direita com o
  card "Projetos" (`projMini()`, linha 460: nome, barra de progresso, prazo) e o card
  "Ritual do dia" (linha 504), que hoje é só um par de botões estáticos: *Checkpoint* e
  *Análise*.
- **Projetos** (`renderProjetos()`, linha 516) — um card por projeto: objetivo, badge de
  situação vinda do último checkpoint (`no rumo` / `em risco` / `desviando`), contagem de
  tarefas, prazo e uma timeline vertical de check-ins.
- Clicar numa tarefa abre um popover de edição (projeto, tags, prazo, esforço).

Convenções visuais já existentes, que valem reaproveitar:

| Classe / função | O que é |
|---|---|
| `.pbar` / `.pbar-fill` / `.pmini-prog` | barra de progresso fina (5px) + contador mono |
| `.sbadge` / `.sbadge.ok` / `.sbadge.risk` | badge de status (verde / âmbar) |
| `.proj-dot` / `.proj-chip` | ponto e chip coloridos por projeto |
| `projClass(id)` (linha 339) | paleta de 6 cores, `'c' + (id % 6)` |
| `statusCls(tag)` (linha 334) | mapeia o status do checkpoint para a classe do badge |
| `.scard` / `.scard-title` / `.scard-sub` | card da sidebar |
| `.ptl` / `.ptl-item` / `.ptl-dot` | timeline vertical de checkpoints |

## 4. O contrato de dados atual (real, não idealizado)

`GET /api/state` devolve exatamente isto — saída real da API com uma rotina cadastrada:

```json
{
  "today": "2026-08-02",
  "day": "2026-08-02",
  "user_name": "",
  "model": "qwen3.5-4b",
  "tasks": [
    {
      "id": 1,
      "title": "Baixar arquivo da operadora",
      "priority": null,
      "done": false,
      "day": "2026-08-02",
      "due": null,
      "tags": [],
      "effort": null,
      "source": "manual",
      "project_id": 1,
      "project_name": "Janela de Comissões — 2026-08"
    }
  ],
  "projects": [],
  "routine_runs": [
    {
      "id": 1,
      "name": "Janela de Comissões — 2026-08",
      "goal": "comissões conciliadas e comunicadas no SLA",
      "deadline": "2026-08-05",
      "active": true,
      "tag": "em risco",
      "tasks": { "total": 2, "done": 0 },
      "timeline": [
        {
          "date": "2026-08-02",
          "status": "em risco",
          "summary": "Em risco — etapa de reconciliação não executada, impedindo o SLA hoje."
        }
      ]
    }
  ]
}
```

Pontos importantes:

- `projects` e `routine_runs` vêm em **chaves separadas**, no mesmo formato. Os ciclos foram
  deliberadamente tirados de `projects` para não poluir a aba Projetos; hoje o front só os usa
  no `<select>` do popover de edição (sem isso, editar uma tarefa de ciclo apagaria o vínculo
  em silêncio).
- `tag` é o veredito do último checkpoint, ou `"sem checkpoint"`, ou `"concluído"`.
- **`tasks` é `done/total` de tarefas soltas** — não sabe nada de etapas.

### O que falta na API

**A API ainda não expõe etapas.** Nenhum campo de `stage` aparece em `/api/state`: nem nos
projetos, nem nos ciclos, nem nas tarefas. Isso é trabalho de backend que vou fazer *depois*
de o design estar definido, para modelar o payload conforme a tela precisar — e não o
contrário. A proposta inicial é:

```jsonc
// dentro de cada projeto e de cada routine_run:
"stages": [
  {
    "id": 3,
    "name": "Reconciliar com o extrato",
    "position": 2,
    "deadline": "2026-08-02",
    "done": false,
    "overdue": true,                          // calculado no servidor
    "done_criteria": "diferença < 0,01% contra o extrato do banco",
    "tasks": { "total": 4, "done": 1 }
  }
],
"stages_progress": { "total": 3, "done": 1 }

// dentro de cada task:
"stage_id": 3,
"stage_name": "Reconciliar com o extrato"
```

**Diga se esse formato não serve.** Ajustar o payload é barato agora; refazer a tela depois
não é.

## 5. Os problemas de design a resolver

### 5.1 Como projeto e ciclo se distinguem visualmente

O ciclo tem coisas que projeto não tem — período, SLA, e o fato de que **volta**. Precisa de
tratamento próprio: aba nova? seção separada dentro de Projetos? outra forma de card? A
decisão precisa deixar óbvio, em um relance, que "Janela de Comissões — 2026-08" não é uma
entrega que alguém escolheu fazer neste mês.

### 5.2 Como a etapa aparece dentro do card

Hoje o card mostra `done/total` de tarefas — número que diz pouco. Com etapas dá para mostrar
onde a entrega está: qual etapa está aberta, se está atrasada, o que falta para fechá-la.
Perguntas: as etapas aparecem sempre ou só ao expandir? A barra de progresso passa a ser por
etapa em vez de por tarefa? Como mostrar uma etapa **atrasada** sem que a tela vire um mar de
alerta vermelho quando três ciclos estão abertos?

### 5.3 O critério de pronto

É o dado mais valioso e o mais difícil de posicionar: é texto livre, pode ser longo, e só
importa no momento em que você decide se a etapa fechou. Tooltip? Segunda linha? Só na tela
de detalhe? Só no fluxo do checkpoint?

### 5.4 O "Ritual do dia" deixa de ser estático

Hoje são dois botões fixos na sidebar. Com rotinas, esse card pode virar o lugar onde o app
diz o que **hoje** exige: *"Janela de Comissões — falta reconciliar, prazo hoje"*, ou
*"julho ainda está aberto"*. É provavelmente a maior oportunidade da tela — e a que mais
pode incomodar se for agressiva demais.

### 5.5 Etapa no popover de edição da tarefa

O popover já tem projeto, tags, prazo e esforço. A etapa entra ali, e o campo depende do
projeto escolhido (trocar de projeto invalida a etapa — é uma regra de negócio real, não
detalhe de implementação).

### 5.6 O que a "Análise" ganha: run vs change

Com a separação, o `wa review` passa a poder dizer **"71% do seu mês foi rotina, 29% foi
projeto"**. Vale explicar o porquê: este app nasceu de um feedback do gestor sobre
organização e entregas, e essa é possivelmente a métrica mais defensável que ele produz — é
a conversa de *"não estou entregando projeto porque a operação come o mês"*, com número. Não
é uma métrica a mais no rodapé; provavelmente é a manchete da aba Análise.

## 6. Restrições

1. **Vanilla JS, arquivo único, sem build.** Nada de React, bundler ou npm.
2. **Sem rede.** Nenhuma fonte, CSS ou script externo — o app roda 100% local e offline.
3. **Tema claro/escuro** já existe por variáveis CSS; qualquer cor nova entra como variável.
4. **Densidade.** O usuário é engenheiro de dados e olha isso entre execuções de pipeline. A
   tela deve responder rápido a "o que está atrasado?" — não é um dashboard para contemplar.
5. **Nada de scroll horizontal**; a largura de referência é 1160px.
6. **Português do Brasil** em tudo que é visível.

## 7. O que trazer de volta

Protótipo `.dc.html` atualizado com as telas afetadas, mais:

- a decisão sobre distinção projeto × ciclo, com a razão;
- o card de projeto/ciclo com etapas, nos estados: sem etapas, em dia, com etapa atrasada,
  e ciclo fechado;
- o "Ritual do dia" na versão nova;
- ajustes de contrato de dados que a tela exigir (§4), para eu implementar no backend;
- classes CSS novas, seguindo as convenções da §3.

Não precisa fechar tudo de uma vez — a distinção projeto × ciclo e o card com etapas
destravam a maior parte do trabalho de implementação.
