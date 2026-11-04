# How a project is built: waves, roles and gates

This is the step-by-step for assembling a new project from the template. It applies to the agent who will orchestrate the construction and to whoever will review. If you are an implementer who received a delegation package, read only the section [For the implementer](#for-the-implementer).

The principle: **errors are good for agents.** A type, lint or test error is cheap, local and precise feedback. The construction is designed so that every hole in a contract becomes a gate error, and not a silent bug.

## Roles

| Role | Who it is | What it does |
| --- | --- | --- |
| **Owner** | the person responsible for the project | decides domain, invariants, authorizations and any change to a template rule |
| **Orchestrator model** | the frontier model that leads the main session | builds **almost everything**: survey, tree, contracts, Containers, signatures, docstrings, `run`s, tests, fakes, rehearsal, integration and report |
| **Implementers** | subagents of the same session, running on **intermediate or smaller** models | fill in **only the body** of the methods they received, against tests that already exist |

In the documents, the roles are called frontier model (or orchestrator), intermediate model and smaller model, never by product name. Which concrete model takes each role is an owner decision, written in `AGENTS.md` ("Critics and delegation policy").

Why divide it this way: the orchestrator sees the whole pipeline in one window (the climb through `match`, the Containers, the requests and products), so the architecture decisions stay with it. The implementer does not need global context: with signature, Container fields, effects, failures and tests, a smaller model gets a method body right. The complete table of who can touch what is in [`AGENTS.md`](../../AGENTS.md).

## Overview

```text
Wave 0  Owner            decisions and authorizations (AGENTS.md)
Wave 1  Orchestrator     survey: use cases, products, effects, authorities
Wave 2  Orchestrator     complete skeleton in code + tests + rehearsal    → gates
Wave 3  Implementers     method bodies, in parallel                       → gates per delivery
Wave 4  Orchestrator     review, failure classification, new round        → gates
Wave 5  Orchestrator     integration, authorized real verification, report
```

Each wave only starts with the previous one closed by the gates it requires. If a wave reveals structural absence, go back to Wave 2; do not patch it up in Wave 3.

---

## Wave 0 — the owner decides

Before any code:

1. Copy the template (command in the cookiebook's `RUNBOOK.md`, task A) and run the gates: everything green in the initial state.
2. Fill in the `<!-- FILL IN -->` sections of `AGENTS.md`: what the product is and is not; domain invariants (what each LLM role may know, who has authority over what); provider and model per role; critics and delegation policy (how many implementers per wave, which models, recursive delegation yes or no); authorizations in force (network, paid model, commit).
3. Any change to a template rule (see [template-decisions.md](template-decisions.md)) becomes an entry in the [`architecture-log.md`](architecture-log.md).

**Closes when:** `AGENTS.md` has no `FILL IN` left without an answer, or the owner explicitly marked what stays open.

## Wave 1 — survey (orchestrator)

Produce, from the owner's sources and from the product:

- the list of **use cases**, each as a named request (`<Verb><Object>`: `SaveNote`) and named product (`SavedNote`);
- the **effects** of each case (read, write, network, paid inference) and where they are published;
- the **authorities**: who validates a name, who admits a model proposal, who owns each resource;
- the shared **mechanisms** (the template already brings `_shared/json/*` and `notes/_shared/storage/*`);
- where each package lives in the tree: depth says who uses it, and what two or more neighbours share goes into the `_shared/` of the common ancestor (guide §2). When replacing `notes` with the real domain, decide where `storage/` and `prepare/` go: the `_shared/` of the single domain that writes, or `backend_logic/_shared/` if there are two.

This stays in `.dumps/` as a draft. It is not a parallel document: in Wave 2 it becomes code, and the draft stops being valid.

**Closes when:** every use case has a request, product, effects and a place in the tree.

## Wave 2 — complete skeleton (orchestrator)

The orchestrator writes the entire tree in real code. Order inside each package, from the bottom of the tree up:

1. **`contracts.py`:** request, product, types of the Container fields, `Protocol`s of ports, errors with `Literal` codes, numbers with a role as `NewType`. Everything the type can close, it closes (guide §6): that is the room the implementer will not have to get it wrong.
2. **`container.py`:** fields with declared empties (`None` or typed empty).
3. **`pipeline.py`:** `Pipe` with `get`, the transformation methods and `materialize`. Each method has a final signature, `-> Self` and a complete docstring (`Require …; set …`, effects, failures, guide §3.5). The body of every method that will be delegated is:

   ```python
   def admit_names(self) -> Self:
       """Require stems; set names admitted by the shared note_name authority. No I/O."""
       raise NotImplementedError("notes.list.admit_names")
   ```

   `get` and `materialize` are normally already written by the orchestrator: they are short and define the Container's contract.
4. **`run.py`:** the real composition, with order, branches, locks, `TaskGroup` and `await` on its own line, written by hand (the formatter does not touch `run.py`).
5. **Families:** `type <Family>Request` and `<Family>Response`, `match`/`assert_never`, and one `@overload` per case in `backend_logic/run.py`.
6. **Tests**, written now and not later:
   - one behaviour test per delegated method, using "start in the middle" (guide §12.4): prepares a valid Container at that step, calls the method and checks the written fields and the failures;
   - rehearsals of the real `run`s with typed fakes at the boundaries (model, clock, store in a temporary directory);
   - rejection cases the contract requires.

**Gates that close Wave 2:**

- `uv run ruff check .`, `uv run ruff format --check .` and `uv run mypy .` **green**;
- `tests/gates/test_style.py`, `tests/gates/test_architecture.py` and `tests/gates/test_config.py` **green**;
- the behaviour tests fail **only** with `NotImplementedError("package.method")`. This list of reds is the Wave 3 backlog. Any other failure (import, type, fixture) is a skeleton error and is fixed before delegating.

This is the most expensive and the most important wave. A loose contract here becomes, in Wave 3, an implementer who invents.

## Wave 3 — filling in (implementers)

The orchestrator distributes the backlog into **delegation packages** and fires the session's subagents in parallel, each on an intermediate or smaller model.

Distribution rules:

- **Unit of work:** one method, or a cohesive set of methods of the same `pipeline.py`.
- **One file, one implementer at a time.** Two methods of the same `pipeline.py` go to the same subagent or in series; parallelism only between different files.
- The implementer does **not** receive the whole project: it receives the package below. It may read the files cited in the package, it does not need to explore the rest.
- No recursive delegation, unless the owner decides otherwise.

### Delegation package template

```markdown
## Task: notes.list.admit_names

File (exclusive): backend_logic/notes/list/pipeline.py — only the body of `Pipe.admit_names`.

Signature and contract (do not change):
    def admit_names(self) -> Self:
        """Require stems; set names admitted by the shared note_name authority. No I/O.

        A stem it rejects fails the listing (ValueError): a misnamed file is corruption
        to report, not something to hide by filtering.
        """

Container (backend_logic/notes/list/container.py):
- reads: stems: tuple[str, ...] | None  (required; None → RuntimeError)
- writes: names: tuple[NoteName, ...] | None  (same order as the stems)
- preserves: input, files

Calls: naming.run(stem) — already imported (`lazy from ..name import run as naming`).
Effects: no I/O.
Failures: stems missing → RuntimeError; naming.run raises NoteValidationError →
  ValueError with `from error` (a misnamed file is corruption, not a client error).

Tests that must pass: uv run pytest tests/example/test_notes_list.py
Gates that must pass: uv run ruff check . ; uv run mypy .

Forbidden: changing the signature, docstring, contracts.py, container.py, run.py, tests or
pyproject.toml; adding an import, field, `cast`, `Any` or `# type: ignore`.
If the contract is impossible or incomplete: stop and reply with the "contract" report.
```

### Implementer report

The implementer replies with one of these two formats, and nothing else:

```markdown
### delivered
- method: notes.list.admit_names
- gates: ruff ok · mypy ok · pytest tests/example/test_notes_list.py: 4 passed
```

```markdown
### contract
- method: notes.list.admit_names
- what is missing: the Container has nowhere to keep the rejected stems that the test expects.
- evidence: test/mypy output (copied, not summarized).
```

## Wave 4 — closing each delivery (orchestrator)

For each report:

1. **Run the four gates** on the whole project, not only the package's.
2. **Check the diff:** only lines inside the body of the delegated method may change. Any other changed line in `backend_logic/`, in the tests or in `pyproject.toml` fails the delivery, even with green gates. (Today this is a manual check with `git diff`; there is not yet a mechanical gate for it.)
3. **Classify the failure**, if any (guide §13):
   - **(1) implementation:** contract and wiring existed and the body did not fulfil them → return to the **same** subagent the gate output, without summarizing. The error is the feedback.
   - **(2) architectural omission:** the contract was insufficient (the "contract" report usually falls here) → the orchestrator fixes the skeleton, reruns Wave 2 on that stretch and redistributes.
   - **(3) undistributed capability:** it was never in a delegation package → back to Wave 1/2.
4. If failures (2) and (3) are numerous or coupled, **stop Wave 3** and go back to the design. Do not accumulate conversions, parameters and methods to make the gate go green.

**Closes when:** no test fails with `NotImplementedError`, the four gates are green and every diff has been checked.

## Wave 5 — integration, verification and report (orchestrator)

1. Wire the real consumers (`http_adapter`, `lifespan`) and check that the HTTP adapter enters only through the root.
2. Verification with real components (model, network) **only with explicit authorization** from the owner, under the `-m llm` marker.
3. Write in `architecture-log.md` what changed in structure, with the honest state (absent / rehearsed / implemented / integrated / verified).
4. Report to the owner: what was proven and what was **not**. "Green gates" is not "finished product".

---

## For the implementer

You received a delegation package. Read, in this order:

1. the whole package;
2. the indicated file and method, and the `container.py` and `contracts.py` of the same package;
3. the indicated tests;
4. if in doubt about a name or a rule: guide §3.5 (docstring), §5 (Container), §6 (typing) and §16 (anti-patterns).

Rules:

- Write only the method body. A missing required field becomes `if x is None: raise RuntimeError(...)`, never `assert`.
- Run the indicated gates until they are green. The gate error is your specification: read it and fix it.
- Never change a test, signature, docstring, contract, Container or configuration to make it pass.
- If the contract is impossible, stop and reply with the "contract" report. That is a valid delivery, not a failure.