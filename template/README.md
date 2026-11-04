# agent-project

<!-- FILL IN: project name and purpose. -->

Skeleton in the vertical pipelines style: `backend_logic` (domain, agents, pipelines) and `backend_frontend` (HTTP adaptation). The dependency direction is guarded by `tests/gates/test_architecture.py` and the vocabulary by `tests/gates/test_style.py`. Depth says who uses a package, and what two or more neighbours share lives in the `_shared/` of their common parent. Python 3.15: every top-level import is `lazy` (PEP 810), with a fallback to a normal import described in guide §6.1.

## Map

| Path | What it demonstrates |
| --- | --- |
| `backend_logic/run.py` | **Start reading here.** Single door: `match` over `BackendRequest` descends to each family; each family does the same down to the leaf. |
| `backend_logic/notes/` | Family: `NotesRequest = PrepareResources \| ListNotes \| SaveNote`, dispatch by `match` in `run.py`. |
| `backend_logic/notes/list/` | Minimal process: candidates (`stems`) separated from admitted (`names`); listing only reads, does not create a directory. |
| `backend_logic/notes/save/` | `async` process: lock and branch in `run`, child steps `decode`/`encode` called by `decoding.run`/`encoding.run`, `commit` with receipt, post-commit `NoteResultError`. |
| `backend_logic/notes/prepare/` | Owner of the lifetime resources (`Resources`: store, locks, clock), prepared once in the `lifespan`. |
| `backend_logic/notes/_shared/storage/` | Disk mechanism, for `notes` only: `read` (`Found`/`Missing`), `write` (atomic with `WriteReceipt`), `scan`, `lock` (named locks never evicted) and `_shared/path` (confinement). Grouping: `contracts.py` with `FileStore`, no `run`. |
| `backend_logic/roles/` | Family: `RolesRequest = SummarizeNote \| DigestNotes`. |
| `backend_logic/roles/summarizer/` | Provider-neutral LLM role: `Model` port (Protocol), projection before the prompt, response as a proposal, local admission. Async step on its own `await` line. |
| `backend_logic/roles/digest/` | Real parallelism: `asyncio.TaskGroup` with one `summarizer.run` per note, budget validated before the calls, integration in fixed order after the barrier, a failure cancels the rest. |
| `backend_logic/_shared/json/` | Strict JSON used by storage, LLM roles and the HTTP edge: `decode` (the only boundary with the `Any` of `json.loads`), `encode` and `_shared/validate`. Grouping: `contracts.py` with `JsonValue`, no `run`. |
| `backend_logic/_shared/note_name/` | Authority of the note name, used by `notes` and `roles`. |
| `backend_frontend/` | Routes that enter only through `backend_logic/run.py`; resources prepared in the `lifespan`. |
| `tests/gates/` | **Global gates, every project keeps them unchanged:** style and folder shape (`test_style.py`), dependency direction (`test_architecture.py`), gate configuration (`test_config.py`). They know only `backend_logic`/`backend_frontend`, never the domain. |
| `tests/mechanisms/` | Tests of the shipped mechanisms (`_shared/json`, `notes/_shared/storage`); they move with the mechanism when it changes place. |
| `tests/example/` | Tests of the example domain (`notes`, `roles`, HTTP edge): rehearsals with typed fakes, "start in the middle", concurrency. Deleted together with `notes/` and `roles/`. |
| `tests/support/` | Helpers shared by test folders (`wire_client.py`, an in-process HTTP client); on the pytest `pythonpath`. |

`notes` and `summarizer` are examples: replace them with the real domain while keeping the form. A project's own tests go in one folder per family (`tests/<family>/`), never back into `tests/gates/`.

## Usage

```fish
uv sync
uv run ruff check .; and uv run ruff format --check .; and uv run mypy .; and uv run pytest
```

Linters, formatter, typechecker and tests already come configured in `pyproject.toml`: ruff (rules `E,F,I,N,W,UP,B,C4,SIM`, line 100, `run.py` outside the formatter to preserve the composition ladder), strict mypy (`disallow_any_expr` across the whole project, `Any` only at three registered boundaries, extra checks on; guarded by `tests/gates/test_config.py`) and async pytest with the `llm` marker off. It is project configuration, not editor configuration: keep it.

## Documentation

New agent: start with [`docs/design/reading-order.md`](docs/design/reading-order.md), which gives the reading order by role.

| Document | Purpose |
| --- | --- |
| [`AGENTS.md`](AGENTS.md) | Imperative rules and owner decisions of this project. |
| [`docs/design/reading-order.md`](docs/design/reading-order.md) | What to read, in what order, depending on the role. |
| [`docs/design/vertical-pipelines.md`](docs/design/vertical-pipelines.md) | The complete guide to the style. |
| [`docs/design/vocabulary.md`](docs/design/vocabulary.md) | Defined names, conventions and proposals. |
| [`docs/design/template-decisions.md`](docs/design/template-decisions.md) | Why each template rule exists, the gate that guards it and what it does not prove. |
| [`docs/design/construction.md`](docs/design/construction.md) | Construction in waves: the orchestrator writes almost everything, subagents on intermediate or smaller models fill in the method bodies. |
| [`docs/design/architecture-log.md`](docs/design/architecture-log.md) | Log of this project's decisions (born empty). |