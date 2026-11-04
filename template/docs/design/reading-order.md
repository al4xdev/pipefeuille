# Reading order for a new agent

You have never seen this project. This page says what to read, in what order, and when to stop. Read by role: the orchestrator needs the whole map; the implementer, only their package.

## If you are the orchestrator model (or will review the project)

1. **[`AGENTS.md`](../../AGENTS.md)** — the imperative rules and this project's owner decisions. In conflict with the guide, the owner decisions marked there prevail.
2. The project's **[`README.md`](../../README.md)** — the map: what each folder demonstrates.
3. **The code, by the climb.** Open the files in this order; in each package read `run.py` → `contracts.py` → `container.py` → `pipeline.py`:
   1. `backend_logic/run.py` — the single door and the menu of `@overload`s;
   2. `backend_logic/notes/run.py` — a family: `match` over `PrepareResources | ListNotes | SaveNote`;
   3. `backend_logic/notes/list/` — the minimal process;
   4. `backend_logic/notes/save/` — async process with lock, children `decode`/`encode`, `commit` and receipt;
   5. `backend_logic/notes/prepare/` — the lifetime resources (store, locks, clock);
   6. `backend_logic/roles/summarizer/` and `roles/digest/` — LLM role and parallelism with `TaskGroup`;
   7. the `_shared/` — `backend_logic/_shared/` (`json/`, `note_name/`) and `notes/_shared/storage/`: what neighbours share, one package per operation; first read the `_shared/` block of guide §2;
   8. `http_adapter/` — the HTTP edge, which enters only through the root.
4. **[`vertical-pipelines.md`](vertical-pipelines.md)** (the guide) — §1 to §6 in full; the rest through the table below, when the topic appears.
5. **[`vocabulary.md`](vocabulary.md)** — before naming anything.
6. **[`template-decisions.md`](template-decisions.md)** — the why of each rule and the gate that guards it. Read before thinking about "simplifying" a rule.
7. **[`construction.md`](construction.md)** — how to conduct the waves and assemble the delegation packages.
8. **[`architecture-log.md`](architecture-log.md)** — the decisions already made in this project.
9. **The gates as specification:** `tests/gates/test_style.py`, `tests/gates/test_architecture.py`, `tests/gates/test_config.py`. The test comments cite the guide section that each rule protects (`§2`, `§3.1`…).

Stop here and run the four gates (`AGENTS.md`, "Gates" section) before changing anything.

## If you are an implementer (received a delegation package)

Do not read the whole project. Follow [construction.md → For the implementer](construction.md#for-the-implementer): the package, the method, the `container.py` and `contracts.py` of the same package, and the indicated tests. If you need a rule, consult the guide sections listed there.

## Lookup by topic (guide)

| When you are going to… | Read |
| --- | --- |
| create a package or move one | §2, §7 |
| name a method, type or alias | §3, `vocabulary.md` |
| write or change a `run.py` | §4 (indentation, branches, async, `TaskGroup`) |
| touch a Container | §5 |
| decide a type, or run into `Any` | §6, §6.1, `template-decisions.md` C |
| write, publish or lock something | §9 |
| touch the HTTP adapter | §10 |
| create an LLM role | §11 |
| rehearse, test or delegate | §12, §13, `construction.md` |
| record a decision | §14, `architecture-log.md` |
| review a delivery | §16 (anti-patterns), §17 (checklist) |