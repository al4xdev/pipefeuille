# Contratos para delegação entre modelos — o motivo do cookbook

> **Rascunho bruto, isolado do cookbook.** Registra o motivo explicado pelo dono em 2026-11-04. Ainda não foi destilado nem integrado ao `template/`. A destilação, para reduzir o consumo de tokens, será feita **junto com o dono, no final**. Não mexer no template com base neste arquivo sem essa revisão.

## A ideia central

O erro é bom para agentes. Um erro de tipo, de lint ou de teste é um feedback barato, local e preciso, e um agente consegue corrigi-lo sozinho. Por isso a estrutura do cookbook existe para **transformar furo de contrato em erro de gate**, e não em bug silencioso.

O template atual ainda não é a versão final. O alvo é um **guia para LLMs** montarem um projeto novo em ondas:

1. **Modelo de fronteira (orquestrador):** gera a arquitetura inteira, com contratos, Containers, assinaturas e `run` reais em toda a árvore. Os métodos ficam só **fortemente tipados**, com corpo `raise NotImplementedError("pacote.metodo")`.
2. **Modelos intermediários ou baratos (implementadores):** vários subagentes em paralelo preenchem os métodos, cada um respeitando as tipagens que recebeu.
3. **Gates:** ruff, mypy estrito e pytest pegam quem furou o contrato. O implementador corrige pelo erro, sem precisar entender o projeto inteiro.

Nomenclatura nos documentos: **modelo de fronteira**, **modelo intermediário** e **modelo barato**. Não usar nomes de produto.

## Quem pode mexer em quê

Regra do dono: a estrutura pertence ao modelo de fronteira. Os modelos intermediários e baratos só mexem no método que receberam por delegação.

| Artefato | Modelo de fronteira | Modelo intermediário / barato |
| --- | --- | --- |
| `run.py` (composição, `match`, `TaskGroup`, locks) | escreve e altera | não toca |
| `contracts.py` (pedidos, produtos, erros, `Literal`, `NewType`, `Protocol`) | escreve e altera | não toca |
| `container.py` (campos e tipos) | escreve e altera | não toca |
| `pipeline.py`: assinatura, docstring "Require …; set …", ordem dos métodos | escreve e altera | não toca |
| `pipeline.py`: **corpo do método delegado** | entrega como `raise NotImplementedError("pacote.metodo")` | **preenche só este corpo** |
| `__init__.py`, estrutura de pastas | escreve | não toca |
| Testes e fixtures do método | escreve (ou aprova) | roda; não altera para passar |
| Gates (`pyproject.toml`: ruff, mypy, pytest) | configura | roda; nunca relaxa |

Se o implementador concluir que o contrato está errado ou incompleto (falta campo, tipo largo demais, erro não declarado), ele **para e reporta ao modelo de fronteira**. Não contorna com `cast`, `# type: ignore`, campo novo ou import extra.

Consequência prática: o gate de delegação pode ser mecânico. O diff de um implementador só pode alterar linhas dentro do corpo do método delegado. Qualquer outra linha alterada em `backend_logic/` reprova a entrega.

## Futuro (não agora): o projeto como JSON

Como toda pasta tem os mesmos 5 arquivos e o mesmo vocabulário, dá para extrair o projeto inteiro para um JSON com uma ferramenta simples, por exemplo via `ast`. O JSON listaria a árvore de pacotes e, para cada pacote:

- o request e o produto;
- os campos do Container;
- os métodos da Pipe, com assinatura, docstring e status (preenchido ou `NotImplementedError`);
- a cadeia do `run`.

Usos possíveis:

- montar o pacote de delegação mínimo de cada método, com menos tokens;
- dar ao modelo de fronteira um mapa compacto do projeto;
- comparar a estrutura antes e depois de uma onda de implementadores.

## Por que isso funciona

- **Visão ponta a ponta numa janela só.** O modelo de fronteira enxerga as pipelines inteiras no mesmo contexto: a subida por `match`, os Containers, os pedidos e os produtos. As decisões de arquitetura ficam com quem tem essa visão completa.
- **O implementador não precisa de contexto global.** Basta a assinatura, os campos do Container que lê e escreve, os efeitos, as falhas e as fixtures. É o item 3 do "Processo" no `AGENTS.md`.
- **Tipagem como especificação.** Quanto mais o modelo de fronteira tipar, menos espaço o modelo barato tem para furar o contrato. A tipagem deixa de ser só higiene e vira o canal de especificação entre modelos.

## Consequência para o template atual

O dono observou que **os contratos atuais não estão fortemente tipados o bastante** para esse uso. Para uso real, o orquestrador precisa tipar o máximo que conseguir. Exemplos de lacunas no template de hoje, a revisar depois:

- `str` cru onde há regra de domínio: `SummarizeNote.language`, `DigestNotes.language`, `SaveNote.name` (string ainda não validada; poderia ter tipo próprio de entrada), `NoteView.title` e `body`, `ModelRequest.system` e `user`.
- `int` cru para orçamentos e limites: `output_tokens`, `max_sentences`, `max_notes`, `revision`, `schema_version`. Um `NewType` ou um tipo com faixa declarada impediria trocar um pelo outro.
- Campos do Container como `X | None` genéricos. O tipo não diz em que etapa o campo passa a existir, e isso só aparece nas docstrings (`Require …; set …`).
- Erros: as subclasses de `ValueError` estão certas, mas a assinatura do `run` não declara quais erros ele pode levantar. Hoje isso fica só na docstring e no guia.

### Já aplicado no template (2026-11-04)

Registrado no `architecture-log.md`. A prova é uma sonda com mypy: um código de erro com erro de digitação e um `schema_version` passado como revisão viraram erros de tipo.

- Códigos de erro como `Literal`: `NoteConflictCode` e `NoteValidationCode`.
- `WritePhase`: as seis fases da escrita atômica.
- `Language = Literal["en", "pt-BR"]`.
- `Revision = NewType("Revision", int)`.
- `NoteView.title: NoteName`.

Ficou de fora, para discutir:

- `NoteDocument` como `TypedDict`: não é atribuível a `JsonValue` sem conversão.
- Orçamentos como `NewType`: `TokenBudget(256)` no `run` pioraria a leitura.
- `SelectLock.kind`: o mecanismo não deveria conhecer o domínio.
- Estágio do Container no tipo.
- Erros declarados na assinatura.

## Perguntas abertas (para a revisão com o dono)

- Até onde tipar sem perder legibilidade? Um `NewType` por campo, `Literal`, ou tipos com validação no construtor?
- Como declarar no contrato o que hoje está nas docstrings (lido, exigido, escrito, efeitos, falhas), de forma que um gate verifique?
- O que o pacote de delegação entregue ao implementador contém, exatamente, e como manter isso pequeno em tokens?
- Qual a granularidade de uma tarefa para o modelo barato: um método, um pacote ou uma etapa?
- Como o modelo de fronteira verifica a onda: só os gates, ou também crítico?