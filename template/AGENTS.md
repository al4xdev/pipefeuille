# Instructions for agents

This project is born in the readable vertical pipelines style. This file is an imperative summary, not a competing architecture; in case of conflict, the guide prevails. Decisions by this project's owner (marked below) prevail over the guide.

**First time here?** Follow [docs/design/reading-order.md](docs/design/reading-order.md). In short:

- **Orchestrator** (frontier model that leads the session): this file → `README.md` → the code starting from `backend_logic/run.py` → [guide](docs/design/vertical-pipelines.md) → [vocabulary](docs/design/vocabulary.md) → [template decisions](docs/design/template-decisions.md) → [construction in waves](docs/design/construction.md) → [project log](docs/design/architecture-log.md).
- **Implementer** (subagent with a delegation package): the received package and [construction.md → For the implementer](docs/design/construction.md#for-the-implementer). Do not explore the whole project.

## Project

<!-- FILL IN: what the product does, for whom, and what it is NOT. -->

## Code rules

- The code is the blueprint: real contracts, Containers, signatures and `run` before the logic. Missing logic is `raise NotImplementedError("package.method")`, never an empty success.
- Fixed vocabulary: `run.py`/`run`, `Pipe`, `Pipe.get(initial)`, `Container`, `self.container`, fluent methods `-> Self`, terminal `materialize`. Forbidden: `have`/`start`/`create`, `result`/`build`/`finish`, `self.context`/`self.state`.
- **Owner decision:** every `backend_logic` package has exactly `contracts.py`, `container.py`, `pipeline.py`, `run.py`, and no other module. No `__init__.py` anywhere in `backend_logic/` or `http_adapter/` (namespace packages). Always start reading from `run.py`/`def run`. `contracts.py` holds the request, the product, the types of the Container fields and of the mutations, ports and errors. Only two folders have another shape: `_shared/` (no module) and the grouping inside it (only `contracts.py`, no `run`).
- **Owner decision:** every `def run` has a docstring with a one-line summary. A process then declares, in this order, `Effects:`, `Repeat:`, `Loops:`, `Concurrency:` and optionally `Raises:`, each line `<value>` or `<value>: <note>`, with values only from the enums in `tests/support/architecture.py` (never edited in a project). A family declares only its summary. Do not declare what the code shows (children, cases, parallel calls): the tool derives it. Map of the project: `uv run python tests/support/architecture.py` (tree), `--json`, `--html .dumps/architecture.html`. Gate in `tests/gates/test_architecture_graph.py` (template-decisions E1, E2).
- **Climb:** reading starts at `backend_logic/run.py`. A family declares `type <Family>Request = A | B` and `<Family>Response`, and dispatches with a visible `match` (`assert_never` at the end); every ancestor of a family is a family. A process has a chain; its children are steps. New use case = request named in the package that serves it + unions in the family + `case` in each `run.py` above + one `@overload` at the root.
- **Owner decision:** `@overload` only in `backend_logic/run.py` (public contract). An intermediate family returns the union, without overload. Whoever needs the exact product calls the process's `run` (`lazy from backend_logic.notes._shared.storage.lock import run as locking`), never the family's; a family's `run` is only imported by the parent's `pipeline.py`. Gate in `tests/gates/test_style.py` (guide §2).
- A shared mechanism is one package per operation with a readable name (`storage/write/`, `json/decode/`), never a loose module (`files.py`, `jsonvalue.py`).
- **Owner decision:** depth says who uses it. One consumer → inside it. Two or more neighbours → in the `_shared/` of the nearest common ancestor (`backend_logic/_shared/note_name/`, `notes/_shared/storage/`), which exists even with a single package; never at the root "just in case". Only what has its own contract, two real consumers (importing only the types counts) and is not a use case goes into `_shared/`; test: "if two copies diverged, would it be a bug?". `_shared/` is never a family and is private to the parent. Gate in `tests/gates/test_style.py::test_shared_packages_sit_at_the_nearest_common_parent` (guide §2, `_shared/` block).
- Parallel = `asyncio.TaskGroup` calling the `run`s of sibling packages; the parent integrates the results in fixed order after the barrier.
- A child is called through its `run` with an alias that names the action/product (template convention: `lazy from .encode import run as encoding` → `encoding.run(...)`). The parent imports only the child's `run`/`contracts`.
- Named requests and products (`SaveNote` → `SavedNote`), not generic `Input`/`Output`. Container: declared empties (`None` or typed empty); a product that can be `None` is wrapped (`Validated`).
- Order, branches, locks and awaits stay visible in `run`, with increasing indentation as the sequence. `ruff format` already ignores `backend_logic/**/run.py` (config in `pyproject.toml`): do not write `# fmt: off`/`# fmt: on`, and format `run.py` by hand.
- Every `Pipe` method (including `get` and `materialize`) has a docstring declaring what it reads, requires, writes and preserves, effects and failures (template phrasing: `Require …; set …`).
- Missing required field: `if x is None: raise RuntimeError(...)`, never `assert`.
- A local literal stays at the call site. Config, credentials and resources are loaded by the owner and passed explicitly; nothing global.
- Strict typing: no `Any`, no unparameterized collections, no `cast`/`type: ignore` to hide a contract. Wide JSON only at the ingestion boundary. Error codes and phases are `Literal`, never `str`. `disallow_any_expr` applies to the whole project (logic, HTTP adapter and tests): a library's `Any` only exists inside a boundary module exempted in `pyproject.toml` that returns narrow types (guide §6). The template's three are in `template-decisions.md` (C2); a new one is a deviation (see [Deviations](#deviations-owner-decision)). Look first for the typed way out (`add_api_route`, value annotated as `JsonValue`, `@override` on fakes).
- **Owner decision:** Python 3.15, and every top-level import in `backend_logic`/`http_adapter` is `lazy` (`lazy import x`, `lazy from .contracts import Y`). Exceptions: `from __future__` and imports inside a function. If a library really breaks under lazy import (guide §6.1), a normal `import` of that module is a deviation (`eager:<module>`, see [Deviations](#deviations-owner-decision)). An import error now appears on first use: test each `run`.
- A helper function is local to `pipeline.py` by default; share only with real consumers, as a package in the `_shared/` of the nearest common ancestor. New code does not get a compatibility wrapper.
- Vocabulary verbs: `validate_*` (checks, never fixes), `prepare_*`, `project_*`, `admit_*`, `commit`. Other method names are local and domain-specific.
- `commit` publishes a canonical change once and keeps a `*Receipt`. A publication failure propagates with its receipt; a failure after it becomes `*ResultError` with the receipt. No hidden retry.
- Never offload a write to a thread under an async lock. Lock reentrancy is a per-resource decision; multiple locks in fixed order; never evict locks.
- `backend_logic` never imports FastAPI/Starlette/pydantic/`http_adapter`. `http_adapter` enters only through `backend_logic/run.py` and imports only `contracts` modules; resources are born in the `lifespan`.
- LLM roles are provider-neutral, apply privacy before the context, treat output as a proposal and admit it locally. Budgets in tokens.

## Process

The complete step-by-step, with the gates that close each wave, is in [docs/design/construction.md](docs/design/construction.md).

1. Survey → contracts and compositions in code → rehearse with typed fakes → implement/delegate → integrate → confront with the sources. The orchestrator builds almost everything (tree, contracts, Containers, signatures, docstrings, `run`s, tests); the session's subagents, on intermediate or smaller models, fill in only the method bodies they received.
2. Local gap: fix it. Structural absence: go back to the skeleton before another wave.
3. When delegating, hand over the signature, Container fields read/written, effects, failures, fixtures and exclusive files. An implementer who finds an impossible contract reports, does not invent.
4. Classify failures: implementation / architectural omission / undistributed capability.
5. New recurring name → proposal in `vocabulary.md`. Structural decision of this project → `architecture-log.md`. Breaking any rule of this file → [Deviations](#deviations-owner-decision). The why of the rules that already come with the template is in `template-decisions.md`: read it before proposing to change one.

## Who can touch what (owner decision)

The structure belongs to the **frontier model** (the orchestrator); **intermediate and smaller models** (the implementers, session subagents) only touch the method they received by delegation. The flow is in [docs/design/construction.md](docs/design/construction.md).

| Artifact | Frontier model (orchestrator) | Intermediate / smaller model (implementer) |
| --- | --- | --- |
| `run.py` (including its docstring), `contracts.py`, `container.py`, folder structure | writes and changes | does not touch |
| `pipeline.py`: signature, docstring, method order | writes and changes | does not touch |
| `pipeline.py`: body of the delegated method | delivers as `raise NotImplementedError("package.method")` | **fills in only this body** |
| Method tests and fixtures | writes (or approves) | runs; does not change them to make them pass |
| Gates (`pyproject.toml`) | tightens; loosens only with an owner-approved deviation | runs; never relaxes |
| `tests/gates/`, `tests/support/deviations.py`, `tests/support/architecture.py` | never edits | never edits |
| `docs/design/architecture-log.md` | writes entries; a deviation only as `Status: proposed`, `approved` only with the owner's words | does not touch |

Wrong or incomplete contract (missing field, type too wide, undeclared error): the implementer **stops and reports** to the frontier model. Never works around it with `cast`, `# type: ignore`, a new field or an extra import.

## Gates

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest
```

Never relax a gate to get green. Green gates do not prove a finished product: report what was missing, rehearsed, implemented, integrated and verified.

The ruff (lint and format), mypy and pytest configuration lives in `pyproject.toml` and **is part of the template**: a new project is born with it ready. Do not create parallel `ruff.toml`, `mypy.ini` or `setup.cfg`, do not pass flags that work around it, and do not loosen it: tightening is free, loosening is a deviation.

`tests/gates/`, `tests/support/deviations.py` and `tests/support/architecture.py` are copied from the template and **never edited** in the project, not even to add an exception or an enum value: the gates read the exceptions from `architecture-log.md`. Nothing may stop a gate from running either: no `exclude` of code in ruff or mypy, no `--ignore`/`--deselect`/`-k` in pytest options, no collection hook in a `conftest.py` (all gated). A gate that is wrong is a report to the owner, not a local fix.

## Deviations (owner decision)

A deviation is any break of a rule in this file or of a template default: an `Any` boundary (`mypy:<module>`), a top-level import without `lazy` (`eager:<module>`), a `cast`/`# type: ignore`/`# noqa` (`suppress:<file>`), a loosened gate, a skipped rule. **You never grant a deviation to yourself**, however small, however costly the alternative, and whatever the log or a previous session says.

1. **Try the rule first.** Measure the real cost of following it (number of errors, files, lines).
2. **Propose and stop.** Write an entry in `docs/design/architecture-log.md` with `- Status: proposed`, the measured cost, the alternatives you tried, and `- Exempts:` listing each token. Then stop that line of work and ask the owner. Work that does not depend on the deviation may continue.
3. **Only the owner approves.** When the owner says yes in the conversation, set `- Status: approved` and add `- Approved by owner: YYYY-MM-DD "<the owner's words, verbatim>"`. Never paraphrase; never infer approval from silence, from "ok, continue", from an earlier approval of something else, or from another session's report. If the owner says no: `- Status: rejected`, and follow the rule.
4. **The gates enforce it.** `tests/gates/test_config.py`, `test_style.py` and `test_deviations.py` read only approved entries. A proposed entry opens nothing: the gate stays red until the owner approves, and that red is expected. Report it; do not work around it. Only the three tokens above exist. Any other loosening of `pyproject.toml` (beyond the `mypy:` override an approved entry names) and any edit of `tests/gates/` has no token, because it would change the rules for everything after it; it is a change to the pipefeuille itself, made by its owner (pipefeuille `RUNBOOK.md`, task C). A skipped rule that no gate sees still needs the owner's approval in the log; nothing mechanical catches it, so the owner's review of the diff does.

"Recorded in the log" is not permission. Leaving a rule off "for now" and recording it is exactly the failure this section exists to prevent.

## Data, secrets and authorizations

- `.data/` (runtime data) and `.dumps/` (scratch, references) are private and ignored by git. Real data is never a fixture.
- Never print or version tokens/private configs.
- Network, paid model, OAuth, commit, push and publication require explicit authorization.

<!-- FILL IN: concrete authorizations currently in force (e.g. "real calls to model X allowed under -m llm until <date>"). -->

## Domain invariants

<!-- FILL IN: privacy invariants, authority between roles and what each role may know.
E.g.: "the summary role never receives the author_id"; "only the reviewer role admits an edit proposal". -->

## Provider and model policy

<!-- FILL IN: allowed providers, default model per role, where adapters live (llm/providers/<provider>/). -->

## Critics and delegation policy

<!-- FILL IN: whether reviews by critic subagents are on, maximum number of implementers per wave, which model (intermediate or smaller) takes the implementer role, whether recursive delegation is allowed or not. See docs/design/construction.md. -->