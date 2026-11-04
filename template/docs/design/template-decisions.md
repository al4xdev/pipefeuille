# Decisions that already come with the template

This document explains **why** each template rule exists. It compiles the decision record made while the template was being built, rewritten as current state: the rule, the reason, what was measured, the gate that protects it and what that gate does **not** prove.

Who should read: every agent before the first wave (see [reading-order.md](reading-order.md)), and any agent tempted to "simplify" a rule. If a rule here gets in the way of the new project, do not work around it: propose the change to the owner, and the decision goes into the project's [`architecture-log.md`](architecture-log.md).

How to read each entry:

- **Rule:** what the code does today.
- **Why:** the problem the rule solves, almost always actually seen.
- **Gate:** the test or the configuration that fails if the rule is broken.
- **Does not prove:** what remains human or orchestrator-model review.

The complete guide is in [vertical-pipelines.md](vertical-pipelines.md); the names, in [vocabulary.md](vocabulary.md).

---

## A. Shape of the tree

### A1. Five files in every folder, reading starts at `run.py`

- **Rule:** every `backend_logic` package has exactly `__init__.py` (docstring only), `contracts.py`, `container.py`, `pipeline.py` and `run.py`, and no other module. All reading starts at `run.py`/`def run`. The only exceptions are the two forms of A5: `_shared/` (only `__init__.py`) and the grouping inside it (`__init__.py` and `contracts.py`).
- **Why:** in an earlier version, `backend_logic/` had no `run.py`; `codec/jsonvalue.py`, `storage/files.py` and `storage/locks.py` were loose modules with names that do not say what they do; `notes/` had `contracts.py` without `run`. The owner, reading, did not know where to start. With fixed names, whoever does not know the domain still knows where the package runs, what it holds and what it exchanges.
- **Gate:** `tests/gates/test_style.py::test_every_folder_has_the_files_its_kind_requires` (with self-test in `::test_shape_scanner_reports_every_kind`), `::test_no_module_outside_the_mandatory_names`, `::test_package_init_is_a_docstring_without_startup`; `tests/gates/test_architecture.py::test_run_modules_contain_a_real_run_definition`.
- **Does not prove:** that the content of each file is in the right file (a domain type forgotten in `pipeline.py`, for example).

### A2. Climb by families: the root is the single door

- **Rule:** a family declares `type <Family>Request = A | B` and `<Family>Response` in `contracts.py` and dispatches with `match`/`assert_never` in `run.py`. `backend_logic/` is a family, and every ancestor of a family is too. Children of a process are steps, not cases. The frontend enters only through `backend_logic/run.py`.
- **Why:** any use case is found by descending `match` by `match` from a single file. Named requests (`SaveNote`, `PrepareResources`) replaced generic `Input`/`Output` because the request name is readable outside the package.
- **Gate:** `tests/gates/test_style.py::test_every_family_run_dispatches_by_typed_use_case` (family without `match` or family under a process); `tests/example/test_backend_run.py::test_each_family_is_reached_from_the_root`; `tests/gates/test_architecture.py::test_http_enters_only_through_the_root_run`; mypy `exhaustive-match`.
- **Does not prove:** exhaustiveness beyond what `assert_never` and mypy guarantee.

### A3. `@overload` only at the root; the exact product comes from the process

- **Rule:** only `backend_logic/run.py` has `@overload` per use case (the public "menu"). Intermediate families return the union. Whoever needs an exact product imports the **process's** `run` (`lazy from backend_logic.notes._shared.storage.lock import run as locking`); a family's `run` is only imported by the parent's `pipeline.py`.
- **Why:** mypy does not check an overload against each `case`. Measured on a copy: with `run(EncodeValue) -> int` and a body returning `str`, the `run.py` of the family that then dispatched JSON passed clean and only the callers broke. Without any overload, a family's `materialize()` only promises the union, and callers would need `isinstance`. One block at the root, covered by a test that calls each case, leaves a single promise.
- **Gate:** `tests/gates/test_style.py::test_only_the_root_declares_overloads_and_only_parents_call_a_family` (verified against the old version: it listed the 4 families with overload and the 6 shortcuts).
- **Does not prove:** that the root's overloads tell the truth; that is checked only by `tests/example/test_backend_run.py`.
- **Consequence that led to A5:** with this rule, the `storage` and `json` families were left without a caller: everyone called the operation directly. A family that nobody calls is dead code that looks like a door. A5 solved this by taking the mechanisms out of the family role.

### A4. A mechanism is one package per operation

- **Rule:** `_shared/json/{decode,encode}` + `_shared/json/_shared/validate` and `notes/_shared/storage/{read,write,scan,lock}` + `storage/_shared/path`, each operation with the five files. Never `files.py`, `utils.py`, `jsonvalue.py`.
- **Why:** same reason as A1; and a folder name such as `storage/write/` says what happens without opening the file. Alternative discarded: tolerating loose modules for mechanisms.
- **Gate:** the same as A1.
- **Does not prove:** that the split into operations is the best one for another mechanism; that is design.

### A5. Depth says who uses it; shared lives in `_shared/`

- **Rule:** a package used by a single consumer stays inside it. A package used by two or more neighbours, that has its own contract and is **not a use case**, lives in the `_shared/` of their nearest common ancestor. The `_shared/` folder exists even when it holds a single package. `_shared/` is never a family, is private to the parent and only has `__init__.py`; a grouping inside it (`json/`, `storage/`) has `__init__.py` and `contracts.py`, without `run`. Importing only the types of a package counts as use. Guide §2.
- **Why:**
  - The name authority lived only in `save.validate_name`. `save/decode` accepted `"../escaped"` and `list` returned raw stems as `str`. The policy was duplicable, and its place in the tree did not say who used it. A rejected name coming from disk is corruption (`ValueError`, 500), not a client error (`invalid_name`, 422).
  - Later, with the shared package next to the use cases (`notes/name/` beside `list/` and `save/`), the tree did not distinguish infrastructure from use case. And the mechanism families (A3) had no caller.
  - The owner decided to name the shared and tested the fear of "hundreds of `_shared`" against a 201-package codebase built in this style:
    - counting any import, 16 of 76 levels would gain `_shared/`; counting only `run` calls, 10;
    - most would end up with 1 or 2 packages;
    - the big false positive was domain using domain (6 of 10 root packages), hence the condition "is not a use case".
  - `_shared/` always, and not "only with two or more", because an unconditional rule is easier for implementers and the second shared package does not change the path of the first.
  - Alternatives discarded: `utils/` at the root (grows without an owner); shared loose beside the use cases (unreadable); mechanism as a family (no caller).
- **Applied to the template:**
  - `roles/summarizer` uses `NoteName`, so the name moved up to `backend_logic/_shared/note_name/`.
  - Only `notes` touches disk, so `storage/` moved down to `notes/_shared/storage/`, and the lifetime resources became `notes/prepare/`'s (formerly `runtime/application/`).
  - `PrepareResources` is now a case of the `notes` family.
- **Gate:**
  - `tests/gates/test_style.py::test_shared_packages_sit_at_the_nearest_common_parent`, which checks:
    - two consumers per package in `_shared/`;
    - `_shared/` private to the parent;
    - shared outside `_shared/` is flagged.
  - The self-test `::test_placement_scanner_reports_every_rule` covers this gate. Run against the earlier tree, it flagged `json/validate`, `notes/name` and `storage/path`.
  - `::test_every_family_run_dispatches_by_typed_use_case` fails a family or grouping with `<Family>Request` inside `_shared/`.
  - Behaviour: `tests/example/test_notes_name.py`, `tests/example/test_notes_save.py::test_stored_name_passes_the_same_authority_as_save_input`, `tests/example/test_notes_list.py::test_misnamed_file_fails_the_listing_instead_of_disappearing`.
- **Does not prove:**
  - That the package really has its own contract, and is not a promoted convenience function. That is the test "if two copies diverged, would it be a bug?", which stays with the orchestrator's review.
  - That a use case is in the right family.

---

## B. Reading the code

### B1. `run.py` outside the formatter

- **Rule:** `[tool.ruff.format] exclude = ["backend_logic/**/run.py", "docs/**/*.md"]` with `force-exclude = true`. `# fmt: off`/`# fmt: on` forbidden in `backend_logic`. The linter still applies to `run.py`.
- **Why:** the increasing indentation of the chain in `run` communicates sequence, and the formatter would flatten it. Before, each `run.py` repeated `# fmt: off`, which was noise and easy to forget in a new package. Without `force-exclude`, an editor or agent that passes the file path would ignore the exclude. The `.md` files are excluded because ruff formats Python blocks inside Markdown, and the guide quotes `run.py` compositions.
- **Gate:** `tests/gates/test_config.py::test_run_composition_is_left_to_the_author_not_the_formatter`, `tests/gates/test_style.py::test_run_composition_has_no_formatter_escapes`.
- **Does not prove:** that the hand-written `run.py` is well indented.

### B2. `await` on its own line

- **Rule:** an async step is `await pipe.x()` on its own line; the template does not chain after the `await`.
- **Why:** chaining is valid Python, but from the second async step on it becomes `(await (await pipe.a()).b()).c()` and the suspension point disappears in the parentheses. On its own line, the `await` sits at the column of the `async with` and the `if`s, where the reader looks for what can be interrupted.
- **Gate:** none mechanical; review.
- **Does not prove:** —

### B3. Real parallelism with `TaskGroup` (`roles/digest/`)

- **Rule:** parallel is `asyncio.TaskGroup` calling the `run`s of sibling packages, visible in `run`. Budget and preconditions are validated before any paid call; integration happens after the barrier, in request order. The first failure cancels the rest; there is never a partial result.
- **Why:** the guide prescribed the pattern without demonstrating it. Alternative discarded: `gather(return_exceptions=True)`, which would return a partial digest without a contract for that.
- **Gate:** `tests/example/test_roles_digest.py`. The concurrency test hangs if the calls are sequential (the first note's fake waits for the second to finish, under `asyncio.timeout(1)`). Verified by mutation: sequential loop, partial `gather` and removal of `validate_notes` made the tests fail.
- **Does not prove:** concurrency limit against a real provider (there is no semaphore) nor aggregate cost in tokens.

---

## C. Typing

### C1. `Literal` for closed sets, `NewType` for numbers with a role

- **Rule:** `NoteConflictCode`, `NoteValidationCode`, `WritePhase`, `Language` are `Literal`; `Revision` is `NewType`; `NoteView.title` is `NoteName`.
- **Why:** the frontier model types the contracts and smaller models fill in the methods; everything the type does not close is room to break the contract without the gate seeing it. When `Revision` was wired in, mypy pointed to 7 places in the tests where a raw `int` became a revision.
- **Kept on purpose:** budgets (`output_tokens`, `max_*`) as `int` with a name on the parameter (`TokenBudget(256)` worsens the reading of `run`); `SelectLock.kind` as `str` (the mechanism does not depend on the domain); `NoteDocument` without `TypedDict` (it would not be assignable to `JsonValue`); free texts and not-yet-admitted input (`SaveNote.name`).
- **Gate:** mypy; `tests/gates/test_style.py::test_error_codes_and_phases_are_closed_sets` (forbids `code`/`phase` as `str`) and the scanner's self-test.
- **Does not prove:** that other closed sets were discovered; the gate only looks at those two names.

### C2. `Any` only at a registered boundary

- **Rule:** strict mypy with `disallow_any_explicit`, `disallow_any_unimported`, `disallow_any_expr` (whole project, tests included), `warn_unreachable`, `strict_bytes` and the extra codes of `pyproject.toml`. Three modules exempt from `disallow_any_expr`, each narrowing the value before returning it:
  - `backend_logic._shared.json.decode.*`: the `Any` of `json.loads`;
  - `test_config`: the `dict[str, Any]` of `tomllib`;
  - `wire_client`: Starlette's `TestClient` reaches mypy as `Any` (verified with `reveal_type`).
- **Why:** the same as C1. The typed ways out were looked for before exempting: routes through `router.add_api_route` (FastAPI's decorators are typed with `Any`), response bodies annotated as `JsonValue`, fakes with `@override`.
- **Gate:** `tests/gates/test_config.py::test_mypy_gate_keeps_any_out_of_expressions_everywhere` fails if mypy loses `strict`, `disallow_any_expr` or `warn_unreachable`, or if another exemption appears.
- **Does not prove:** that a new library will come typed; each may require another boundary, decided by the owner and recorded in the project's `architecture-log.md`.
- The template's only `# type: ignore`s are `[call-overload, misc]` in `tests/example/test_backend_run.py`, which calls `run` wrongly on purpose to exercise the runtime guard.

### C3. Python 3.15 and every top-level import `lazy`

- **Rule:** `requires-python = ">=3.15"`; every top-level import in `backend_logic` and `backend_frontend` is `lazy` (PEP 810). Exceptions go in `EAGER_IMPORTS` (`tests/gates/test_style.py`) with a reason, and in an `architecture-log.md` entry. `tests/` stays eager.
- **Why:** owner's choice. Importing the root does not load the whole tree: after importing `backend_logic.run`, `notes._shared.storage.write.pipeline` and `roles.digest.run` are not in `sys.modules`.
- **Measured:** CPython 3.15.2 resolved the 37 dependencies. `pyyaml` (via `uvicorn[standard]`) has no cp315 wheel and was compiled without the C extension: it works, slower. The fallback (all `lazy` removed) passed mypy and the tests outside `test_style`. In this build, `-X lazy_imports` has no option to turn it off: the fallback is editing the code.
- **Gate:** `tests/gates/test_style.py::test_every_top_level_import_is_lazy` and its self-test.
- **Does not prove:** that every import path resolves. An import error appears on first use, so each `run` needs to be exercised by some test.

---

## D. Boundaries and effects

### D1. One strict JSON for the three ingestion boundaries

- **Rule:** `_shared/json/decode` is the only JSON reading policy (duplicates, `NaN`/`Infinity`, lone surrogates, depth → `ValueError`), used by storage, by the LLM role and by the HTTP edge. `_shared/json/encode` refuses what the decode would refuse. The HTTP edge reaches it through the root: `DecodeText` and `EncodeValue` are root cases that call the operation directly, without a JSON family.
- **Why:** a critical review reproduced `{"body": "\ud800"}` passing through the HTTP edge and becoming a 500 on write; `"[" * 2000` escaped the summarizer as `RecursionError`; the edge accepted duplicate keys. The policy was duplicated and incomplete.
- **Gate:** `tests/mechanisms/test_storage_json.py`, `tests/example/test_http_notes.py::test_malformed_wire_body_is_rejected_before_the_logical_run`, `tests/example/test_summarizer.py::test_contract_violations_reject_without_a_second_call`.
- **Does not prove:** body size limit nor parsing cost.

### D2. HTTP edge without pydantic; resources in the `lifespan`

- **Rule:** the frontend reads bytes, decodes through the single door (`backend.run(DecodeText(...))`) and checks the wire shape in a dataclass. Store, locks and clock are born in the `lifespan` through `backend.run(PrepareResources(...))`; constructing the app does not touch disk.
- **Why:** `pydantic.BaseModel` models introduce `Any` and fail `disallow_any_explicit`. If the owner wants pydantic at the edge, it is a recorded decision with a gate adjustment; in `backend_logic`, never.
- **Gate:** `tests/example/test_http_notes.py::test_app_construction_touches_no_disk_until_the_lifespan_starts`, `tests/gates/test_architecture.py::test_logic_does_not_import_http`.
- **Does not prove:** transport security, authentication or body limits.

### D3. Validate rejects, never fixes; path confined per segment

- **Rule:** `validate_*` does not `.strip()` nor normalize. A note name is an explicit ASCII set. `storage/path` rejects `""`, `"."`, `"notes/."`, `\`, NUL, absolutes and `..` instead of normalizing them. A document whose `name` does not match the path is not accepted as a predecessor.
- **Why:** `validate_name` did `.strip()` and accepted `"²½"` via `str.isalnum()`; the path accepted `"notes/."`; `notes/a.json` with `name: "b"` was accepted.
- **Gate:** `tests/mechanisms/test_storage_json.py::test_path_rejects_instead_of_normalizing`, `tests/example/test_notes_name.py::test_invalid_names_are_rejected_never_corrected`, `tests/example/test_notes_save.py::test_misfiled_document_is_not_accepted_as_predecessor`.
- **Does not prove:** behaviour with symlinks nor with multiple processes.

### D4. Publication with receipt; failure before and after commit

- **Rule:** `storage/write` publishes with a temporary file in the same directory → flush → fsync → atomic replace → directory fsync, and returns `WriteReceipt` (`NOT_PUBLISHED`, `PUBLISHED_NOT_DURABLE`, `DURABLE`) with the published size. A failure of the publication itself propagates `AtomicWriteError` with the receipt; a failure **after** it becomes `NoteResultError` with the receipt. There is never a hidden retry.
- **Why:** the receipt lost `size_bytes` when the directory fsync failed after the replace; and "failed" without a receipt would lead the caller to rewrite something already published.
- **Gate:** `tests/example/test_notes_save.py::test_directory_fsync_failure_reports_published_bytes`, `::test_failure_after_commit_keeps_the_receipt_and_never_rewrites`, `tests/mechanisms/test_storage_json.py::test_unserializable_value_fails_before_publication`.
- **Does not prove:** real durability on every filesystem; the test simulates the failure.

### D5. Named locks, never evicted, rehearsed with `await` inside

- **Rule:** `storage/lock` returns the same `asyncio.Lock` for the same `(kind, name)` and never removes it. The lock is acquired in `run` (`async with locking.run(SelectLock(...))`), not inside a method.
- **Why:** removing a lock would allow an old waiter and a new lock to overlap. And a test of two concurrent writes does not observe the lock when the steps have no `await`: the old `gather` test only proved "the second creation conflicts", not exclusion.
- **Gate:** `tests/example/test_notes_save.py::test_named_lock_excludes_same_name_and_admits_other_names` (a holder waits inside the lock).
- **Does not prove:** exclusion between processes.

### D6. Style gates have a self-test

- **Rule:** each scanner in `tests/gates/test_style.py` and `tests/gates/test_architecture.py` has a test that runs it against a synthetic violating source.
- **Why:** an import scanner that only read `node.module` passed empty without seeing `from X import a`.
- **Gate:** `test_style_scanner_reports_every_rule`, `test_shape_scanner_reports_every_kind`, `test_placement_scanner_reports_every_rule`, `test_closed_name_scanner_reports_bare_str`, `test_eager_import_scanner_reports_only_top_level_eager_imports`, `test_internal_import_scanner_sees_every_import_form`.
- **Does not prove:** semantics. A style gate does not know whether a docstring tells the truth nor whether a `validate_*` fixes in secret.

### D7. Tests are split by lifetime: gates, mechanisms, example

- **Rule:** `tests/gates/` holds the global gates (style, architecture, config) that every project keeps unchanged; they read only `backend_logic`/`backend_frontend` and mention the domain only inside synthetic self-test strings. `tests/mechanisms/` holds the tests of the shipped mechanisms and moves with them. `tests/example/` holds the example-domain tests and is deleted with `notes/` and `roles/`. A project's own tests go in `tests/<family>/`. Helpers shared by test folders live in `tests/support/`, which is on the pytest `pythonpath`. Test folders have no `__init__.py`.
- **Why:** with every test flat in `tests/`, nothing told a new project which files survive a domain swap; an agent could delete a gate together with the example, or keep example tests that pin the old domain.
- **Measured:** a copy of the template without `tests/example/` gives a clean mypy and 53 passing tests (gates and mechanisms), against 120 with it.
- **Gate:** none mechanical; the measurement above is the evidence. Re-run it after changing a gate.
- **Does not prove:** that a future gate stays domain-free; review a new gate for imports of `notes`/`roles`.