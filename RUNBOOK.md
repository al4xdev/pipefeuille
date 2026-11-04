# Runbook: what to do when entering the cookiebook

This repository has two things: the **guide** to the vertical pipelines style and the **template** (`template/`), a Python project that runs, passes the gates and serves as a seed for new projects. The guide and the docs live inside the template (`template/docs/design/`), because they travel with every copied project.

Before acting, find out what your task is:

| If the request is… | Task |
| --- | --- |
| create a new agent project "in the cookiebook style" | [A. Start a new project](#a-start-a-new-project) |
| work on a project that was already born from the template | [B. Work on a project born from the template](#b-work-on-a-project-born-from-the-template) |
| change the guide itself or the template | [C. Maintain the cookiebook](#c-maintain-the-cookiebook) |
| bring an existing codebase into the cookiebook style | [D. Port an existing project](#d-port-an-existing-project) |

If it is not clear, ask the owner before copying or changing anything.

---

## A. Start a new project

You are the **orchestrator model** (frontier model). You build the structure; implementers (intermediate or smaller models) only fill in method bodies afterwards.

1. **Copy the template** to a new directory, without the caches or the `.venv`, and confirm the green state:

   ```bash
   rsync -a --exclude .venv --exclude '.*_cache' --exclude __pycache__ \
       ~/git/my/cookiebook/template/ <destination>/
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

5. **Replace the example domain.** `notes/` and `roles/` exist to show the form; they go away when the real domain has its own examples, together with `tests/example/`. The mechanisms (`_shared/json/`, `notes/_shared/storage/`, `notes/prepare/`) stay, but **change place** according to real use (guide §2, `_shared/` block); `tests/mechanisms/` follows them (update its imports). The gate `test_shared_packages_sit_at_the_nearest_common_parent` points out the wrong place. Tests layout:
   - `tests/gates/`: global; keep unchanged in every project. They pass without `tests/example/`.
   - `tests/mechanisms/`: moves with the mechanisms.
   - `tests/<family>/`: the project's own tests, one folder per family.
   - `tests/support/`: helpers shared by test folders (on the pytest `pythonpath`).

6. **Record decisions.** Every structural decision of the new project goes into `docs/design/architecture-log.md`, which is born empty. A decision that breaks a template rule is only a **proposal** until the owner approves it in their own words ([`AGENTS.md` → Deviations](template/AGENTS.md#deviations-owner-decision)). `template-decisions.md` and `tests/gates/` do not change in the project: they describe and guard the originating template.

**Do not:** relax a gate to get green, edit `tests/gates/`, grant yourself a deviation, create parallel `ruff.toml`/`mypy.ini`, stray modules outside the five names, a root-level `utils/`, commit or call a paid model without written authorization in `AGENTS.md`.

## B. Work on a project born from the template

The entry point is the project's own `AGENTS.md`, not this file. Follow the track for your role in `docs/design/reading-order.md`:

- **Orchestrator:** the whole map, then the gates as specification.
- **Implementer** (received a delegation package): only the package and [construction.md → For the implementer](template/docs/design/construction.md#for-the-implementer). Do not explore the project. Impossible contract: stop and report.

## C. Maintain the cookiebook

Changing the cookiebook changes every project born from it afterwards. Therefore:

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

Porting is where following a rule costs the most, and so where an agent is most tempted to switch one off "for now". The target is the same as task A: every gate of the template green, with no deviation the owner has not approved in their own words. You are the orchestrator model.

1. **Start from a copy of the template, not from the old tree.** Copy as in task A (step 1) into the destination and confirm the green state. `pyproject.toml`, `tests/gates/` and `tests/support/` come from the template and are never edited; do not bring the old project's linter or type checker settings.
2. **Measure before moving code.** Against the old code, collect the numbers each gate would report and write them in `.dumps/tasks/` (never in the project): `Any` expressions under `disallow_any_expr`, `cast`/`# type: ignore`/`# noqa` per file, JSON parsing outside a single decoder (`json.loads`, `json.load`, `model_validate_json`…), top-level imports that would not survive `lazy`, modules outside the five names.
3. **Propose the deviations as one list, then stop.** For each rule you believe cannot be followed, write a `Status: proposed` entry in `docs/design/architecture-log.md` with the measured cost, the alternatives tried and the `Exempts:` tokens ([`AGENTS.md` → Deviations](template/AGENTS.md#deviations-owner-decision)). Show the list to the owner and wait. Do not port the affected code until each entry is approved or rejected. A cost being high is not an argument the agent may settle alone.
4. **Migrate in the order that removes the most deviations:**
   1. **JSON first:** every parse goes through `_shared/json/decode` (via `backend.run(DecodeText(...))` at the HTTP edge). This alone removes most `Any` expressions, because `json.loads` is where they come from.
   2. **Boundaries next:** each remaining library that hands over `Any` gets its own boundary package that narrows the value; each is a `mypy:<module>` proposal.
   3. **`Any` last:** what is left is the project's own code; it is typed, not exempted.
   The HTTP layer becomes `http_adapter/`, whatever it was called before, and is covered by the `lazy` gate like `backend_logic/`.
5. **No gate turned off "for now".** A gate that cannot pass yet stays red and is reported with the count. There is no temporary exemption, no ratchet file, no `per-file-ignores`; if the owner wants a staged migration, they approve each exemption explicitly, and the entry says what removes it.
6. **Close as task A:** the four gates green, `tests/gates/` identical to the template's (`diff -r <template>/tests/gates tests/gates` is empty), and a report to the owner with what was ported, what was proposed, what was approved and what is still red.