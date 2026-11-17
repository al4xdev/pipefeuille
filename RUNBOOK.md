# Runbook: what to do when entering the pipefeuille

This repository has two things: the **guide** to the vertical pipelines style and the **template** (`template/`), a Python project that runs, passes the gates and serves as a seed for new projects. The guide and the docs live inside the template (`template/docs/design/`), because they travel with every copied project.

Before acting, find out what your task is:

| If the request is… | Task |
| --- | --- |
| create a new agent project "in the pipefeuille style" | [A. Start a new project](#a-start-a-new-project) |
| work on a project that was already born from the template | [B. Work on a project born from the template](#b-work-on-a-project-born-from-the-template) |
| change the guide itself or the template | [C. Maintain the pipefeuille](#c-maintain-the-pipefeuille) |
| bring an existing codebase into the pipefeuille style | [D. Port an existing project](#d-port-an-existing-project) |

If it is not clear, ask the owner before copying or changing anything.

---

## A. Start a new project

You are the **orchestrator model** (frontier model). You build the structure; implementers (intermediate or smaller models) only fill in method bodies afterwards.

1. **Copy the template** to a new directory, without the caches or the `.venv`, and confirm the green state:

   ```bash
   rsync -a --exclude .venv --exclude '.*_cache' --exclude __pycache__ \
       ~/git/my/pipefeuille/template/ <destination>/
   cd <destination>
   git init
   uv sync
   uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest
   ```

   If any gate fails right after the copy, stop and report: the template is broken, not the project.

2. **Read, in this order:** `<destination>/AGENTS.md` and then [`docs/design/reading-order.md`](template/docs/design/reading-order.md), on the orchestrator track. Do not skip `template-decisions.md`: it explains why each rule exists and keeps you from "simplifying" one of them.

3. **Wave 0, with the owner.** Rename `name` in `pyproject.toml`. The `<!-- FILL IN -->` sections of `AGENTS.md` belong to the owner: project, invariants, provider and model, critics and delegation, authorizations. Ask for whatever is missing; never invent an answer. Whatever the owner leaves open stays marked that way in the file itself.

4. **Waves 1 to 5:** follow [`construction.md`](template/docs/design/construction.md). In short:
   - survey use cases, products, effects and authorities;
   - write the complete skeleton in code (contracts, Containers, `run`, docstrings, tests, fakes) with `NotImplementedError` bodies, and rehearse;
   - delegate the bodies; review each delivery through the gates and the diff;
   - integrate and report.

   For the map of the project at any moment, run `uv run python tests/support/architecture.py` (tree, for you) or `--html .dumps/architecture.html` (for the owner); never draw the tree by hand.

5. **Replace the example domain.** `notes/` and `roles/` exist to show the form; they go away when the real domain has its own examples, together with `tests/example/`. The mechanisms (`_shared/json/`, `notes/_shared/storage/`, `notes/prepare/`) stay, but **change place** according to real use (guide §2, `_shared/` block); `tests/mechanisms/` follows them (update its imports). The gate `test_shared_packages_sit_at_the_nearest_common_parent` points out the wrong place. Tests layout:
   - `tests/gates/`: global; keep unchanged in every project. They pass without `tests/example/`.
   - `tests/mechanisms/`: moves with the mechanisms.
   - `tests/<family>/`: the project's own tests, one folder per family.
   - `tests/support/`: helpers shared by test folders (on the pytest `pythonpath`).

6. **Record decisions.** Every structural decision of the new project goes into `docs/design/architecture-log.md`, which is born empty. A decision that breaks a template rule is only a **proposal** until the owner approves it in their own words ([`AGENTS.md` → Deviations](template/AGENTS.md#deviations-owner-decision)). `template-decisions.md` and `tests/gates/` do not change in the project: they describe and guard the originating template.

**Do not:** relax a gate to get green, edit `tests/gates/`, grant yourself a deviation, create parallel `ruff.toml`/`mypy.ini`, stray modules outside the four names (or an `__init__.py`), an enum value added to `tests/support/architecture.py`, a root-level `utils/`, commit or call a paid model without written authorization in `AGENTS.md`.

## B. Work on a project born from the template

The entry point is the project's own `AGENTS.md`, not this file. Follow the track for your role in `docs/design/reading-order.md`:

- **Orchestrator:** the whole map, then the gates as specification.
- **Implementer** (received a delegation package): only the package and [construction.md → For the implementer](template/docs/design/construction.md#for-the-implementer). Do not explore the project. Impossible contract: stop and report.

## C. Maintain the pipefeuille

Changing the pipefeuille changes every project born from it afterwards. Therefore:

1. **Owner decision first.** A new or changed rule needs explicit approval. It goes into [`template-decisions.md`](template/docs/design/template-decisions.md) with rule, why, measurement, gate and "does not prove". The template's `architecture-log.md` stays empty: it belongs to the new project.
2. **Code and docs go together.** A rule that changes the code changes, in the same change:
   - the guide ([`vertical-pipelines.md`](template/docs/design/vertical-pipelines.md));
   - the vocabulary, if there is a new name;
   - `template-decisions.md`;
   - the imperative summary in `template/AGENTS.md`;
   - `reading-order.md` and the READMEs, if the map changed.
3. **Every mechanical rule gets a gate, and every gate gets a self-test.** The self-test runs the scanner against a synthetic source or tree that violates the rule and checks the exact list of violations. A gate without a self-test can pass empty.
4. **Measure before adopting.** When there is doubt whether a rule scales, measure on a real codebase and record the number in `template-decisions.md`, without naming the originating project.
5. **Close:** the four gates green inside `template/`; no broken markdown links; and no mention of an old path, searching for the names you just changed.

   ```bash
   cd template
   uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest
   ```

The docs are written for LLMs, not for humans: be precise and literal, cite real paths and test names, and do not call models by product name (use frontier, intermediate and smaller model).

## D. Port an existing project

If the destination must **behave like** the old app and you will rewrite its code rather than move it, also follow [`skills/reverse-engineering/SKILL.md`](skills/reverse-engineering/SKILL.md) to learn the old behavior by observation; the steps below still apply to the gates.

Porting is where following a rule costs the most, and so where an agent is most tempted to switch one off "for now". The target is the same as task A: every gate of the template green, with no deviation the owner has not approved in their own words or through a written delegation reviewed by a critic. You are the orchestrator model.

1. **Start from a copy of the template, not from the old tree.** Copy as in task A (step 1) into the destination and confirm the green state. `pyproject.toml`, `tests/gates/` and `tests/support/` come from the template and are never edited; do not bring the old project's linter or type checker settings. If the old code must keep running until the port lands, it goes into a quarantine beside the project, never into it ([below](#legacy-that-must-keep-running-while-it-is-ported-quarantine-and-frozen-goldens)).
2. **Measure before moving code.** Against the old code, collect the numbers each gate would report and write them in `.dumps/tasks/` (never in the project): `Any` expressions under `disallow_any_expr`, `cast`/`# type: ignore`/`# noqa` per file, JSON parsing outside a single decoder (`json.loads`, `json.load`, `model_validate_json`…), top-level imports that would not survive `lazy`, modules outside the four names, `__init__.py` files with code in them, imports of libraries the project does not declare, and calls of `importlib.import_module`/`__import__`.
3. **Propose the deviations as one list, then stop.** For each rule you believe cannot be followed, write a `Status: proposed` entry in `docs/design/architecture-log.md` with the measured cost, the alternatives tried and the `Exempts:` tokens ([`AGENTS.md` → Deviations](template/AGENTS.md#deviations-owner-decision)). Show the list to the owner and wait. Do not port the affected code until each entry is approved or rejected. A cost being high is not an argument the agent may settle alone. If the owner has delegated approvals in writing, you may approve an entry the delegation's words cover, only after an independent critic subagent reviewed it, with `- Approved by delegation:` and `- Critic:` ([`AGENTS.md` → Deviations](template/AGENTS.md#deviations-owner-decision), item 4); never for the template's own rules, and never by reading a delegation into "continue".
4. **Migrate in the order that removes the most deviations:**
   1. **JSON first:** every parse goes through `_shared/json/decode` (via `backend.run(DecodeText(...))` at the HTTP edge). This alone removes most `Any` expressions, because `json.loads` is where they come from.
   2. **Boundaries next:** each remaining library that hands over `Any` is typed first, with the recipes of [`template-decisions.md` C2](template/docs/design/template-decisions.md#c2-type-first-a-librarys-any-is-typed-before-any-exemption) (annotate `object` and narrow, specialised generics, the typed call, a stub in `tests/support/`); only a module that still cannot be typed, with its measured error count, is a `mypy:<module>` proposal. Never load a library by name to get past its types (D9).
   3. **`Any` last:** what is left is the project's own code; it is typed, not exempted.
   The HTTP layer becomes `http_adapter/`, whatever it was called before, and is covered by the `lazy` gate like `backend_logic/`.
5. **No gate turned off "for now".** A gate that cannot pass yet stays red and is reported with the count. There is no temporary exemption, no ratchet file, no `per-file-ignores`; if the owner wants a staged migration, they approve each exemption explicitly, and the entry says what removes it.
6. **Close as task A:** the four gates green, `tests/gates/` identical to the template's (`diff -r <template>/tests/gates tests/gates` is empty), no quarantine left (below), and a report to the owner with what was ported, what was proposed, what was approved (and how: by the owner, or by delegation with its critic) and what is still red.

### Legacy that must keep running while it is ported: quarantine and frozen goldens

Sometimes the old code has to keep serving while the port is written: rewriting it first would delay the move for code the port deletes anyway. That is an owner decision, recorded as a log entry before any import, and it follows the technique below. Without that entry, the old code stays outside the project (a private snapshot under `.dumps/`, as in the reverse-engineering skill).

**Quarantine: imported legacy code, outside the governed root, with an exit criterion.**

1. **Never inside the governed root.** The governed root is the folder that holds the template's `pyproject.toml`; ruff, mypy and every gate read all of it, their excludes are gated (`tests/gates/test_config.py`), a nested `pyproject.toml` fails `test_pyproject_is_the_only_tool_configuration`, and no token excludes a folder. So the imported code lives beside the root: a sibling folder of the repository (e.g. `<repo>/quarantine/<name>/`, with the project at `<repo>/<project>/`) or its own checkout pinned to a commit. It keeps its own `pyproject.toml`, interpreter, lockfile and tests, run by its own commands; nothing of the template's gates reads it, and nothing of it is changed except what the import needs.
2. **One explicit table, one gate that it is exactly that folder.** A project-owned test (in `tests/<family>/`, e.g. `tests/quarantine/test_quarantine.py`; never `tests/gates/`) holds the only list, e.g. `QUARANTINE = {"<name>": "../quarantine/<name>"}` (paths from the governed root), and asserts:
   - the table is exactly that literal (a quarantine that can widen silently is no exception);
   - the folder exists and holds exactly what was imported (its package, its tests, its project files: list the names);
   - no module of `backend_logic/` or `http_adapter/` imports the quarantined package, and no folder or module of the governed root carries the quarantined package's name. The port talks to the quarantine only through its external interface (HTTP, CLI, files), as a separate process.
   Give the test a self-test on a synthetic tree, as for every gate (task C, step 3).
3. **The log entry.** `Status` and approval as a deviation (by the owner, or by delegation with a critic), `Exempts: none` (the template's gates open nothing for it), the origin (repository and commit of the snapshot), what was renamed, where the table and its test are, the commands that check the quarantine itself, and `- Exit criterion:` naming the change that ends it: the port of the logic lands, and that same change deletes the quarantine folder, the table, its test and the quarantine's own steps in any script or pipeline.
4. **Deletion closes it.** When the exit criterion is met, add a new entry recording it (what was deleted, with commits) and fill in the quarantine entry's `Later result`; do not rewrite the old entry.

**Differential oracle with frozen goldens: the port holds the legacy answers, byte for byte.**

1. **One oracle per behaviour that must not change** (a parser, a rule, a computed report). Its **legacy half** runs the old code; its **port half** runs the project's `backend_logic.run` with the same input. Both serialize each answer with one serializer, written down (e.g. JSON with fixed key order and separators).
2. **Seeded synthetic inputs.** The legacy half generates its inputs from a seed and a size (never real data), covering the branches the code has (empty and populated, each error, each optional part). It runs only in the quarantine's own process and interpreter: the governed project never imports it, and its tests never run it (skill, step 8).
3. **Freeze before deleting.** Before the quarantine is deleted, run each legacy half once and keep its cases (input and answer, one JSON line each), compressed, as test fixtures of the project: e.g. `tests/<family>/goldens/<oracle>.jsonl.gz`, with a `README.md` beside them giving the legacy repository and commit, the generator command, the seeds, the sizes and case counts, the serializer, and the SHA-256 of each file. The inputs are in the goldens, so the test needs nothing of the legacy to run.
4. **The port holds them byte for byte.** A project test per oracle reads its golden file (decoding each line through the project's single JSON decoder, `_shared/json/decode`, never `json.loads`, whose `Any` fails `disallow_any_expr`), runs the port on each input and compares the serialized answer with the golden bytes. A difference is a regression of the port or a decision of the owner; the goldens are never regenerated to make a test pass, and once the legacy is deleted they cannot be.
5. **Prove each oracle can fail.** One deliberate mutation of the port per oracle (a changed boundary, a dropped branch) must turn its golden test red; record the mutation and the failing test in the closing entry, and revert it.

These oracles do not prove what the goldens did not cover: inputs beyond the seeds and sizes frozen, live dependencies, or any data the legacy kept outside its code. Say so in the closing entry.
