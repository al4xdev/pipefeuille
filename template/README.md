# agent-project

<!-- PREENCHER: nome e propósito do projeto. -->

Esqueleto no estilo de pipelines verticais: `backend_logic` (domínio, agentes, pipelines) e `backend_frontend` (adaptação HTTP). A direção de dependência é guardada por `tests/test_architecture.py` e o vocabulário por `tests/test_style.py`. Cada pasta é um pacote; a profundidade diz quem o usa. Python 3.15: todo import de topo é `lazy` (PEP 810), com fallback para import normal descrito no guia §6.1.

## Mapa

| Caminho | O que demonstra |
| --- | --- |
| `backend_logic/run.py` | **Comece a ler aqui.** Porta única: `match` sobre `BackendRequest` desce a cada família; cada família faz o mesmo até a folha. |
| `backend_logic/notes/` | Família: `NotesRequest = ListNotes \| SaveNote`, despacho por `match` no `run.py`. |
| `backend_logic/notes/list/` | Processo mínimo: candidatos (`stems`) separados de admitidos (`names`); listagem só lê, não cria diretório. |
| `backend_logic/notes/name/` | Autoridade compartilhada no nível dos irmãos que a usam (`list`, `save`, `save/decode`). |
| `backend_logic/notes/save/` | Processo `async`: lock e branch no `run`, etapas filhas `decode`/`encode` chamadas por `decoding.run`/`encoding.run`, `commit` com recibo, `NoteResultError` pós-commit. |
| `backend_logic/roles/` | Família: `RolesRequest = SummarizeNote \| DigestNotes`. |
| `backend_logic/roles/summarizer/` | Papel LLM provider-neutral: porta `Model` (Protocol), projeção antes do prompt, resposta como proposta, admissão local. Etapa async em linha `await` própria. |
| `backend_logic/roles/digest/` | Paralelismo real: `asyncio.TaskGroup` com um `summarizer.run` por nota, orçamento validado antes das chamadas, integração em ordem fixa depois da barreira, falha cancela o resto. |
| `backend_logic/runtime/application/` | Dono dos recursos de lifetime (`Resources`). |
| `backend_logic/json/` | Família de mecanismo, um pacote por operação: `validate`, `decode` (única fronteira com o `Any` do `json.loads`), `encode`. |
| `backend_logic/storage/` | Família de mecanismo: `path` (confinamento), `read` (`Found`/`Missing`), `write` (atômica com `WriteReceipt`), `scan`, `lock` (locks nomeados nunca evictados). |
| `backend_frontend/` | Rotas que entram só por `backend_logic/run.py`; recursos preparados no `lifespan`. |
| `tests/` | Arquitetura por AST, ensaios com fakes tipados, "começar no meio", concorrência, borda HTTP. |

`notes` e `summarizer` são exemplos: substitua pelo domínio real mantendo a forma.

## Uso

```fish
uv sync
uv run ruff check .; and uv run ruff format --check .; and uv run mypy .; and uv run pytest
```

Linters, formatter, typechecker e testes já vêm configurados no `pyproject.toml`: ruff (regras `E,F,I,N,W,UP,B,C4,SIM`, linha 100, `run.py` fora do formatter para preservar a escada da composição), mypy estrito (sem `Any`, com `disallow_any_expr` em `backend_logic`) e pytest assíncrono com o marcador `llm` desligado. É configuração do projeto, não do editor: mantenha-a.

Leia `AGENTS.md` e `docs/design/vertical-pipelines.md` antes de mexer em código.