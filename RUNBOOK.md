# Runbook: what to do when entering the cookiebook

This repository has two things: the **guide** to the vertical pipelines style and the **template** (`template/`), a Python project that runs, passes the gates and serves as a seed for new projects. The guide and the docs live inside the template (`template/docs/design/`), because they travel with every copied project.

Before acting, find out what your task is:

| If the request is… | Task |
| --- | --- |
| create a new agent project "in the cookiebook style" | [A. Start a new project](#a-start-a-new-project) |
| work on a project that was already born from the template | [B. Work on a project born from the template](#b-work-on-a-project-born-from-the-template) |
| change the guide itself or the template | [C. Maintain the cookiebook](#c-maintain-the-cookiebook) |

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

5. **Replace the example domain.** `notes/` and `roles/` exist to show the form; they go away when the real domain has its own examples, together with their tests. The mechanisms (`_shared/json/`, `notes/_shared/storage/`, `notes/prepare/`) stay, but **change place** according to real use (guide §2, `_shared/` block). The gate `test_shared_packages_sit_at_the_nearest_common_parent` points out the wrong place.

6. **Record decisions.** Every structural decision of the new project goes into `docs/design/architecture-log.md`, which is born empty. `template-decisions.md` does not change in the project: it describes the originating template.

**Do not:** relax a gate to get green, create parallel `ruff.toml`/`mypy.ini`, stray modules outside the five names, a root-level `utils/`, commit or call a paid model without written authorization in `AGENTS.md`.

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