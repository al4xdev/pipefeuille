# Project vocabulary

Recurring names and their limits. This page records meanings; it does not create mandatory phases. Using a name in the code does not promote it to a standard: only the project owner moves a proposal to "Defined".

New agent: read this whole page before naming anything. If the name you want to use is not here and is not a local domain name (§3.3 of the guide), stop and propose it in the last section.

## Defined by the owner

The core of the style. A new project is born with them and does not vary them.

| Name | Meaning | Limit |
| --- | --- | --- |
| `run.py` / `run` | Public entry and complete composition of the level (`def` or `async def`). | Not a re-export. |
| `Pipe` | Fluent object local to a package. | Always `Pipe`; the package gives the domain. |
| `get(initial)` | Factory with the initial preparation. | Not a getter. Aliases `have`/`start`/`create` forbidden. |
| `Container` | Typed dataclass of the intermediate state, fixed form, declared empties (initial `None` is legitimate; typed empty too). | Not a DTO, prompt or persisted schema. |
| `self.container` | The only place for intermediates. | `self.context`/`self.state` forbidden. |
| `materialize` | Terminal that returns the typed output. | `result`/`build`/`finish` forbidden. |

## Verbs and suffixes (accepted starting point)

Verbs: `validate_*`, `prepare_*`, `project_*`, `admit_*`, `commit` — meanings in §3.3 of the guide. Other method names (`resolve_*`, `read_*`, `decode_*`, `publish_*`…) are readable local names, not vocabulary.

Suffixes: `*Definition`, `*Candidate`/`Proposed*`, `Admitted*`/`Checked*`, `*Draft`, `*View`, `*Document`, `*Receipt`, `*State`, `*Entity`, `*Error`/`*ResultError` — meanings in §3.4 of the guide. There is no generic `Input`/`Output`: requests and products are named (below).

Reading: `None` in the Container = step not executed; `Missing` = observed absence; `Found` = completed read.

## Template conventions

The why of each one, and the gate that guards it, is in [template-decisions.md](template-decisions.md).

| Convention | Limit |
| --- | --- |
| Child called by the module with an alias: `lazy from .encode import run as encoding` → `encoding.run(...)` | The alias names the action or the product (`encoding`, `naming`, `locating`); there is no gerund rule. The form `<alias>.run(...)` is fixed. |
| Docstring `Require …; set …; effects; failures` | The requirement is semantic (read/required/written/preserved/effects); the sentence is style. |
| Five mandatory files in every `backend_logic` package (`__init__`, `contracts`, `container`, `pipeline`, `run`) and no other module name | Owner decision. Readability: any reader knows where the package runs (`run.py`, `def run`) without knowing the domain. Only `_shared/` and grouping have another shape (rows below). |
| `_shared/`: folder with the packages used by two or more neighbours, at their nearest common ancestor | Owner decision. Only `__init__.py`; exists even with a single package; never a family; private to the parent. Only what has its own contract and is not a use case goes in ("if two copies diverged, would it be a bug?"). Not `utils/`: a convenience function stays local, even duplicated. |
| Grouping: child of `_shared/` without `run.py` (`_shared/json/`, `notes/_shared/storage/`) | `__init__.py` and `contracts.py` with the value that all operations exchange (`JsonValue`, `FileStore`); no `run`, no `match`. Whoever needs it calls the operation directly. |
| Named request `<Verb><Object>` (`SaveNote`, `ListNotes`, `DecodeText`, `WriteDocument`) and named product (`SavedNote`, `NoteNames`, `WriteReceipt`) | Replaces `Input`/`Output`. The type lives in the package that serves it. |
| Family: `type <Family>Request = A \| B` in `contracts.py` and a visible `match` in `run.py`, returning `<Family>Response` | The root `backend_logic/` is a family; every ancestor of a family is one too. Children of a process (`save/decode`) are steps, not cases. A family imports contracts from the children; a child never imports the family. `@overload` per case only at the root (public contract); whoever needs the exact product calls the process's `run`, and a family's `run` is only called by the parent. |
| `Validated(value)` in the family's Container | Wraps a product that can be `None` (JSON `null`) so it is not confused with "branch did not run". |
| Mechanism as one package per operation: `_shared/json/{decode,encode}` (+ `_shared/validate`), `notes/_shared/storage/{read,write,scan,lock}` (+ `_shared/path`) | Never a loose module (`files.py`, `jsonvalue.py`). `json/` is in the root `_shared/` because storage, LLM roles and the HTTP edge use it; `storage/` in the one of `notes` because only notes touch disk. Strict JSON policy: duplicates, NaN, surrogates, depth → `ValueError`. |
| Frontend enters only through `backend_logic/run.py` and imports only `contracts` modules | Resources prepared in the `lifespan` by `backend.run(PrepareResources(...))`, kept in a frontend `ResourceSlot`. HTTP body through strict JSON (`backend.run(DecodeText(...))`), without pydantic (gate choice; the style does not impose a form on the HTTP framework). |
| Shared authority (`_shared/note_name/`) | Every boundary that receives a name — input, read document, listed file, LLM role — goes through it; rejection of read data is corruption (`ValueError`), not a client error. |
| Error code and phase as `type <X>Code = Literal[...]` / `type <X>Phase = Literal[...]` in the `contracts.py` of the error's owner (`NoteConflictCode`, `NoteValidationCode`, `WritePhase`) | Closed set: a code shown to the client is a contract, and a new code changes the type. Gate in `tests/gates/test_style.py` forbids `code`/`phase` annotated as `str` in `backend_logic`. |
| Number with its own role as `NewType` (`Revision`) | Constructing does not validate; the step that admits constructs (`Revision(current.revision + 1)`). Call budgets (`max_*`, `output_tokens`) stay `int` with a name on the parameter, so the `run` stays readable. |
| Vocabulary rules verified by `tests/gates/test_style.py` | The test only guarantees what is mechanical; the semantics (what each `validate_*` actually checks) remains review. |

## Proposals under observation

| Name | Where it appeared | Proposed meaning | Limit / doubt |
| --- | --- | --- | --- |
| `Resources` | `backend_logic/notes/prepare` | Application lifetime resources with one owner. | Not a session nor a request container; does not accumulate methods. Today they all belong to `notes`; with a second domain, each prepares its own, or the common resource moves up together with the mechanism. |
| `require_object` | `notes/save/decode` | Require a JSON object with exact keys. | Shape, not semantic admission. |

<!-- When adding: name, where it appeared, meaning, what it does NOT mean. -->