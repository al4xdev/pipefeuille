# Reference guide: vertical pipelines, readability first

> The code is the blueprint itself. The skeleton must be typed and **rehearsed**, not merely exist. Each package tells a complete story at its level; the transformations work on a local `Container` until `materialize` delivers the output.

This guide applies to any agent project born from this template. What is a domain decision of each project (invariants, provider, critics policy) stays in its `AGENTS.md`; section 18 lists what the owner of a new project needs to decide.

**Authority:** this guide and the [vocabulary](vocabulary.md) define the pattern; the template's code is the executable example. If the code and the guide diverge, the guide prevails and the divergence is a bug to record. The summary in `AGENTS.md` is not a competing architecture; owner decisions marked in it prevail over the guide.

**First time here?** Follow the reading order in [reading-order.md](reading-order.md). To learn how the project is built in waves (who writes what), read [construction.md](construction.md). The why of each template rule, with the gate that guards it, is in [template-decisions.md](template-decisions.md).

---

## 1. Principles in one line

1. **The code is the blueprint.** Real packages, types, Containers, signatures and compositions come before the logic. A tree in Markdown does not replace code.
2. **Read from top to bottom like a calculation.** Readability beats mechanical DRY, short functions and few parameters.
3. **Strict typing bounds the implementer's freedom.** The more the contract says, the less the agent guesses.
4. **Rehearse before delegating.** The skeleton runs with typed fakes and coherent data crossing the real wiring.
5. **Complete vertical packages, at any useful depth.** Each `run` tells the whole story of its level.
6. **Fixed, visible order.** No step engine, orchestration DSL or hidden effect queue.
7. **Explicit state.** Configuration and resources are loaded by the owner and passed as arguments; no global `CLIENT`/`STATE`/`SETTINGS`.
8. **Status honesty.** Green typing, green tests and mocks do not prove a finished product. Say what is absent, rehearsed, implemented, integrated and verified.

Clean Code, Clean Architecture, DRY or immutability are not applied out of obligation. A long, coherent function, a repeated composition, a literal in the parameter or an argument that "could be fetched internally" can be deliberate reading choices.

---

## 2. Anatomy of a package

```text
notes/save/
├── __init__.py     # one-line docstring; no I/O, config or startup on import
├── contracts.py    # types that go in and out, types of the Container fields, ports, errors
├── container.py    # @dataclass Container: fixed shape, declared empty fields (None or typed empty)
├── pipeline.py     # class Pipe: get(), transformations that return Self, materialize()
├── run.py          # def run / async def run: the visible composition, public entry
└── encode/         # child: another complete package, with its own Container
    ├── __init__.py
    ├── contracts.py
    ├── container.py
    ├── pipeline.py
    └── run.py
```

| File | Role | Is not |
| --- | --- | --- |
| `run.py` | Where the package runs: `def run` is the public entry and the complete composition of that level. Always start reading from it. | A re-export of another module. Every `run.py` defines a real `run` (the architecture test guarantees it). |
| `contracts.py` | The types the package exchanges and keeps: the request that comes in (`SaveNote`), the product that goes out (`SavedNote`), the types of the Container fields and of the mutations (`CurrentRead`, `NoteDocument`), `Protocol`s of ports and errors. Each type lives in the package that produces or admits it (`NoteName` in `_shared/note_name/`, `NoteRecord` in `notes/save/`). | An HTTP DTO, a bag of types for the whole project, a place for logic. |
| `container.py` | Fixed local state, filled progressively. It is also the boundary for "start in the middle" fixtures. | Configuration, megacontext, public DTO. |
| `pipeline.py` | `Pipe` and its transformation methods. | A place to hide the sequence; the order stays in `run`. |
| `__init__.py` | Identifies the package. | A place for startup, config reading, connection or plugin. |

**The five names are mandatory in every `backend_logic` package, and no other module name exists** (owner decision of this template; see [template-decisions.md](template-decisions.md)). The reason is readability: whoever opens a folder knowing nothing about the domain — what is `codec`? what does `jsonvalue` do? — still knows where to start (`run.py`, `def run`), what the package keeps (`container.py`) and what it exchanges (`contracts.py`). A shared mechanism does not become a loose module (`files.py`, `locks.py`, `jsonvalue.py`): it becomes one package per operation, with a readable name (`storage/write/`, `storage/lock/`, `json/decode/`). The only two folders that are not complete packages are `_shared/` and the groupings inside it (below). `tests/gates/test_style.py` guarantees the shape of each kind of folder and the absence of any other module.

**Depth says who uses it; `_shared/` says it is shared.** The tree is the architecture, and a package's **place** declares who uses it:

- Used by a single package: stays **inside** it, as a child (`save/decode/` only serves `save`).
- Used by two or more neighbours: goes to the **`_shared/` of their nearest common ancestor**. Never to the root "just in case", and never loose beside the use cases.
- `_shared/` exists whenever there is a shared package at that level, even if it is only one. The unconditional rule is easier to follow (and to check) than "only when there are two", and the second shared package enters the folder without changing the path of the first.

What counts as shared (the three conditions hold together):

1. **Has its own contract:** typed request and product and a rule with an owner (path confinement, name policy, atomic write). A convenience function is not a package: it stays local in `pipeline.py`, and duplicating three lines is cheaper than coupling two packages.
2. **Has two or more real consumers** among the children of that level, measured by the gate. Importing only the types (`contracts.py`) also counts: whoever uses the type depends on the rule of whoever defines it.
3. **Is not a use case:** no `<Family>Request` names it. Domain using domain (one family calling another) is **not** sharing; each family stays in its place.

The practical test to decide condition 1: **if two copies of this diverged, would it be a bug?** Two name policies or two ways of writing to disk, yes: it is authority or mechanism, goes to `_shared/`. Two ways of formatting a log message, no: it stays local, even duplicated.

```text
backend_logic/
├── run.py              # the single door: match over BackendRequest
├── contracts.py        # BackendRequest = NotesRequest | RolesRequest | DecodeText | EncodeValue
├── _shared/            # used by more than one branch of the root
│   ├── json/           # grouping: contracts.py with JsonValue; no run, no match
│   │   ├── _shared/
│   │   │   └── validate/   # decode and encode use it
│   │   ├── decode/
│   │   └── encode/
│   └── note_name/      # name authority: notes and roles use it
├── notes/              # family: PrepareResources | ListNotes | SaveNote
│   ├── _shared/        # used by more than one process of notes
│   │   └── storage/    # grouping: contracts.py with FileStore
│   │       ├── _shared/
│   │       │   └── path/   # read, write and scan use it
│   │       ├── read/
│   │       ├── write/
│   │       ├── scan/
│   │       └── lock/
│   ├── prepare/        # lifetime resources: store, locks, clock
│   ├── list/
│   └── save/
│       ├── decode/     # only save reads the old document → inside save
│       └── encode/     # only save writes → inside save
└── roles/              # family: LLM roles
    ├── summarizer/
    └── digest/
```

Three folder shapes, and only three:

| Folder | Files | What it is |
| --- | --- | --- |
| package | the five | family, process or step; has `run` |
| `_shared/` | only `__init__.py` (docstring) | shelf; not a code package |
| grouping (child of `_shared/` without `run.py`) | `__init__.py` and `contracts.py` | gathers the operations of a mechanism (`json/`, `storage/`) and keeps the value they all exchange (`JsonValue`, `FileStore`); must have at least one subpackage |

Rules of `_shared/`, all checked by `tests/gates/test_style.py`:

- **Never a family.** Nothing inside `_shared/` declares `<Family>Request` or has a `match`; the root never dispatches it as a family. Whoever needs it calls the operation's `run` directly (`decoding.run(DecodeText(...))`). This is also security: if the root dispatched `WriteDocument`, the HTTP adapter would write any file, skipping the rules of `notes`.
- **It is private to the owner.** Only whoever is inside the parent of a `_shared/` imports it: `roles/` does not reach `notes/_shared/storage/`. The type that a consumer outside the mechanism needs (`FileStore`) lives in the grouping's `contracts.py`, not in a `_shared/` internal to it.
- **Needs two consumers.** A package in `_shared/` used by a single neighbour moves down inside it.
- **Shared outside `_shared/` is flagged.** A package that is not a use case, used by two neighbours or by someone outside its parent, needs to go to a `_shared/`.

Reading the import path already tells the story: `from .encode import run` is "my child"; `from .._shared.path import run` is "a piece that my siblings and I share". When a second consumer appears in another branch, the package **moves up** to the `_shared/` of the new common ancestor, and the gate points to each import to change. When the last consumer goes away, it **moves down** again. In the template this has already happened once: the note name started in `notes/`, but `roles/summarizer` also uses `NoteName`, so it moved up to `backend_logic/_shared/note_name/`.

**Measured on a large project, before adopting.** It was measured on a codebase of 201 packages and 76 levels with children, built in this style before `_shared/` existed. Counting any import, only 16 levels (21%) would gain `_shared/`; counting only `run` calls, 10 levels (13%). Most would end up with 1 or 2 packages. They were not hundreds. The real risk the measurement showed was another: at the root, 6 of 10 packages were "shared" only because one domain uses another. That is why condition 3 is mandatory, and not a detail. The script stays outside the template; the gate in `test_style.py` does the same count.

**The climb: family and process.** There are two kinds of package, and `contracts.py` says which:

- A **family** declares `type <Family>Request = A | B` (e.g. `NotesRequest = PrepareResources | ListNotes | SaveNote`). Its `run.py` receives the typed request and a visible `match` descends to the child that serves it. The root `backend_logic/` is a family, and every ancestor of a family is too, so the reading of any use case starts at `backend_logic/run.py` and descends `match` by `match` to a leaf.
- A **process** has a chain of steps in `run.py`. Children of a process (`save/decode`, `save/encode`) are its steps, not use cases, and do not need `match`.

```python
# backend_logic/notes/run.py
async def run(initial: NotesRequest, *, resources: Resources | None) -> NotesResponse:
    pipe = Pipe.get(initial)
    match initial:
        case PrepareResources():
            pipe.prepare_resources(initial)
        case ListNotes():
            if resources is None:
                raise RuntimeError("listing notes requires the prepared resources")
            pipe.list_notes(initial, resources=resources)
        case SaveNote():
            if resources is None:
                raise RuntimeError("saving a note requires the prepared resources")
            await pipe.save_note(initial, resources=resources)
        case _:
            assert_never(initial)
    return pipe.materialize()
```

Each case calls a method of the family's `Pipe` that delegates to the child's `run` and stores the product in the Container. An intermediate family **only dispatches**: it returns the `<Family>Response` union declared in `contracts.py` and has no `@overload`. The family's `contracts.py` only imports the children's contracts, and the children never import the family's: this way there is no cycle. When a legitimate product can be `None` (JSON `null`), the Container keeps it wrapped (`Validated(value)`), so that "the branch ran and returned `None`" is not confused with "the branch did not run".

**Overload only at the root; the exact product comes from the process.**

- `backend_logic/run.py` has one `@overload` per use case. It is the public contract, read from top to bottom as the backend's menu: each request, what it requires and what it returns. The HTTP adapter needs it to receive `NoteNames`, and not the union.
- Whoever, inside the backend, needs an exact product calls the `run` of the **process** that produces it (`lazy from backend_logic._shared.json.encode import run as encoding`, `lazy from backend_logic.notes._shared.storage.lock import run as locking`), never the family's. The process's `materialize()` already returns the exact type, and mypy checks that against the body.
- A family's `run` is only imported by the parent's `pipeline.py`, that is, in the climb.
- Reason: an overload is a promise that mypy does **not** check against each `case`. In a test with `run(EncodeValue) -> int`, with the body returning `str`, the `run.py` of the family that dispatched JSON passed clean and only the callers broke. One block only, at the root and covered by `tests/example/test_backend_run.py`, leaves fewer unverified promises than one block per family.
- `tests/gates/test_style.py` fails an overload in a family that is not the root and an import of a family's `run` outside the parent.

### 2.1. Minimal complete example

`contracts.py`

```python
@dataclass(frozen=True)
class ListNotes:
    """List every stored note name. No client input: the directory is server-owned."""


@dataclass(frozen=True)
class NoteNames:
    """Sorted, admitted note names without the JSON suffix; no document contents."""

    names: tuple[NoteName, ...]
```

`container.py`

```python
@dataclass
class Container:
    input: ListNotes | None = None
    files: tuple[str, ...] | None = None
    stems: tuple[str, ...] | None = None  # candidates, not yet admitted
    names: tuple[NoteName, ...] | None = None  # admitted by _shared/note_name
```

`pipeline.py`

```python
class Pipe:
    def __init__(self) -> None:
        self.container = Container()

    @classmethod
    def get(cls, initial: ListNotes) -> Self:
        """Set input unchanged; the directory is chosen by run, not by the caller."""
        pipe = cls()
        pipe.container.input = initial
        return pipe

    def scan_directory(self, *, store: FileStore, relative: str) -> Self:
        """Set files directly beneath relative through storage. Read-only I/O."""
        self.container.files = scanning.run(ScanDirectory(store, relative))
        return self

    def admit_names(self) -> Self:
        """Require stems; set names admitted by the shared note_name authority. No I/O."""
        ...
        self.container.names = tuple(naming.run(stem) for stem in stems)
        return self

    def materialize(self) -> NoteNames:
        """Require completed names, including a legitimately empty tuple; return NoteNames."""
        names = self.container.names
        if names is None:
            raise RuntimeError("note names are required")
        return NoteNames(names=names)
```

`run.py`

```python
def run(initial: ListNotes, *, store: FileStore) -> NoteNames:
    return (
        Pipe
            .get(initial)
                .scan_directory(store=store, relative="notes")
                    .select_stems(suffix=".json")
                        .admit_names()
                            .sort_names()
                                .materialize()
    )
```

The template in `backend_logic/notes/` contains this complete example, an asynchronous process with children, lock, commit and receipt (`save/`), the lifetime resources (`prepare/`), the disk mechanism in `notes/_shared/storage/` and the family that dispatches among them (`notes/run.py`). The name authority is in `backend_logic/_shared/note_name/`, because `roles` also uses it. Path confinement and I/O do not live in `list`: they belong to `storage/_shared/path` and `storage/scan`, called by `scanning.run(ScanDirectory(...))` (`lazy from backend_logic.notes._shared.storage.scan import run as scanning`).

---

## 3. Canonical vocabulary

### 3.1. Defined names (do not vary)

| Name | Single meaning |
| --- | --- |
| `run.py` / `run(...)` | Public entry and complete composition of the level, including `async def run`. |
| `Pipe` | Local fluent object. Always called `Pipe`; the package gives the domain. |
| `get(initial)` | Factory with the declared initial preparation. Reads as "the process **receives** such a thing". Not a property getter. |
| `Container` | Typed dataclass, fixed shape, progressive filling. |
| `self.container` | The only place for intermediates. No loose `self.prompt`, `self.response`. |
| Fluent methods | Transform the container and return `Self`. |
| `materialize(...)` | Terminal: returns the typed output, not `self` nor the whole container. |

**Forbidden:** aliases that split the language — `have`/`start`/`create` in place of `get`; `result`/`build`/`finish` in place of `materialize`; `self.context`/`self.state` in place of `self.container`. A domain type called `CallResult` is allowed: a type name is not a terminal method.

### 3.2. Calling a child

The parent imports the child's `run` **module** with an alias that names the action or the product of that process, and calls `<alias>.run(...)`. The gerund (`encoding`, `reading`, `locking`) is the template's custom, not a rule: `naming`, `validating` and `locating` also name the action. What does not vary is the form `<alias>.run(...)`, which makes visible at the call site that another process begins there:

```python
lazy from .encode import run as encoding              # child (lazy: §6.1)
lazy from .._shared.path import run as locating       # piece shared with the siblings
lazy from backend_logic.notes._shared.storage.write import run as writing  # direct operation

...
self.container.document = encoding.run(self.container.record)
```

What matters: it is visible in the reading that another complete process begins there, with its own Container, and the parent imports `run`/`contracts` of the child, never `pipeline` or internal helpers.

### 3.3. Verbs with consistent meaning

They are not mandatory phases. The vocabulary has only **five** verbs (`validate_*`, `prepare_*`, `project_*`, `admit_*`, `commit`); when they appear, they mean this:

| Verb | Means | Does not mean |
| --- | --- | --- |
| `validate_*` | Check a contract and fail explicitly. | Fix, complete or invent values. |
| `prepare_*` | Prepare a value/resource used later. | Absence of I/O — declare effects in the docstring. |
| `project_*` | Build a bounded view of existing data. | Widen the audience or turn opinion into fact. |
| `admit_*` | Accept a proposal according to that domain's authority. | Parsing; and it is different from `commit`. |
| `commit` | Publish a canonical change **once**, keeping an explicit receipt/result. | Update a local field; nor a generic label for network or inference. |

Everything else is **readable local names**, not vocabulary: in the template, `resolve_path`, `read_current`, `scan_directory`, `select_stems`, `sort_names`, `decode_reply`, `encode_record`; in a real project, effects with a domain name such as `open_response` or `publish_checkpoint`. They do not become a universal framework. If one of them repeats with the same meaning in several packages, propose it in `vocabulary.md`.

### 3.4. Type suffixes (use only when the meaning exists)

| Suffix | Meaning | Example |
| --- | --- | --- |
| `<Verb><Object>` (request) / `<Family>Request` | Typed use case that enters a `run`, named by what it asks for; the family unites the children's requests in a `type <Family>Request = A \| B`. Replaces the generic `Input`/`Output`: the request name is readable outside the package. | `SaveNote`, `ListNotes`, `NotesRequest` |
| `*Definition` | Authored configuration not yet materialized. | `ScenarioDefinition` |
| `*Candidate` / `Proposed*` | Data **not yet admitted**. | `UpdateCandidate`, `ProposedEvent` |
| `Admitted*` / `Checked*` | Marks the completion of a specific admission/check. | `AdmittedSchema`, `CheckedSubmission` |
| `*Draft` | Isolated copy to mutate before the commit. | `UndoDraft`, `InputDraft` |
| `*View` | View projected for a consumer (owner, reader). | `PresetView` |
| `*Document` | Serialized form at the external boundary. | `PrivateConfigDocument` |
| `*Receipt` | Evidence of the result of an effect — does **not** imply success or durability. | `WriteReceipt` |
| `*State` | Canonical state or closed vocabulary of the domain. | `SessionState` |
| `*Entity` | Canonical entity typed by kind (discriminated union). | `ActorEntity` |
| `*Error` / `*ResultError` | Failure. `*ResultError` = terminal failure **after completed work**, which does not authorize retry/replay: it preserves the receipt when there was publication (`PresetResultError`) or marks a non-retryable internal failure without a receipt (`ValueResultError`, `CaptureResultError`). | `PresetResultError`, `ValueResultError` |

Reading states that must not be confused: `None` in the Container = **step not executed**; `Missing` = observed absence; `Found` = completed read (even if the content is `null`). For steps: `stage` = current attempt; `completed_stage` = call that returned.

Nominal identities (`NewType`) distinguish values that cannot be swapped (`ActorId` ≠ `SessionId`), but constructing a `NewType` **validates nothing**; validation is a step of its own.

### 3.5. Method docstring = local contract

The requirement is **semantic**: each method declares fields read, required, written and preserved, and its effects and failures. Free prose also works ("Reads input; fills prompt; does no I/O…"). This template uses a short phrasing in English, which is a **template choice**, not a mandatory formula:

```python
def read_current(self, *, store: FileStore) -> Self:
    """Require name and builtin protection; set current_read. Read-only I/O; no publication."""


def commit(self, *, store: FileStore) -> Self:
    """Require path/document and named lock; publish once and retain WriteReceipt.

    Propagate AtomicWriteError unchanged. No retry.
    """
```

`Require …` (fields read/required) · `set …` (fields written) · allowed/forbidden effects · failures. `-> Self` alone is not a contract: the Container's fields are also inputs and outputs.

### 3.6. New names

A new recurring name goes to `docs/design/vocabulary.md` in the **proposals** section, with meaning and limit. Only the project owner promotes a proposal to a defined name. Using a name in the code does not make it a standard.

---

## 4. Composition in `run`

### 4.1. Semantic indentation

Deepening the indentation communicates sequence/dependency. The formatter would flatten this ladder, so **the template's `pyproject.toml` excludes `backend_logic/**/run.py` from `ruff format`** (with `force-exclude = true`, so that it also applies when an editor or agent passes the file path). No `run.py` needs `# fmt: off`/`# fmt: on`, and `tests/gates/test_style.py` forbids those escapes in `backend_logic`. The linter still applies to `run.py` (imports, line length, names, bugs); whoever writes the `run` is responsible for its form. The `run` snippets quoted in `docs/**/*.md` stay outside the formatter for the same reason. All the rest of the code follows the formatter.

### 4.2. Branches, loops and locks stay in `run`

```python
async def run(
    initial: SaveNote, *, store: FileStore, locks: LockRegistry, clock: Clock
) -> SavedNote:
    pipe = (
        Pipe
            .get(initial)
                .validate_name()
                    .resolve_path(directory="notes", suffix=".json")
    )
    if pipe.container.name is None:
        raise RuntimeError("note save requires validated name before locking")
    async with locking.run(SelectLock(locks, kind="note", name=pipe.container.name)):
        pipe.read_current(store=store)
        if initial.replace:
            pipe.admit_replacement()
        else:
            pipe.admit_creation(initial_revision=1)
        (
            pipe
                .read_time(clock=clock)
                    .prepare_record(schema_version=1)
                        .encode_record()
                            .commit(store=store)
        )
        try:
            return pipe.materialize()
        except Exception as error:
            if pipe.container.receipt is None:
                raise
            raise NoteResultError(pipe.container.receipt) from error
```

Note: the lock is acquired in `run`, not hidden in a method; the branch is a readable `if`; the failure after the commit becomes `*ResultError` with the receipt, so nobody redoes work already published.

### 4.3. Async

`def`/`async def` according to the work; awaits visible. Python does not chain methods over an un-awaited coroutine, so **an async method goes on its own `await pipe.x()` line**, and the ladder restarts at `pipe` right below (`backend_logic/roles/summarizer/run.py`):

```python
pipe = (
    Pipe
        .get(initial)
            .project_note()
                .prepare_prompt(language=initial.language)
                    .prepare_request(output_tokens=256, response_mode="structured")
)
await pipe.call(model=model)
return (
    pipe
        .decode_reply()
            .admit_summary(max_sentences=3)
                .materialize()
)
```

Chaining after the `await` is valid Python (`(await pipe.call(model=model)).decode_reply()…`), but **this template does not use it** (template choice for readability; the owner may revisit it in `architecture-log.md`): with one async step it looks fluent; with two it becomes `(await (await pipe.a()).b()).c()`, and the suspension point disappears in the middle of the parentheses. On its own line, the `await` sits at the same column as the `async with` and the `if`s of the `run`, where the reader looks for what can be interrupted — which matters for locks and cancellation. Coroutine-proxy or metaclass to keep fluency remain forbidden.

### 4.4. Parallelism

Parallel is the parent calling **sibling packages at the same time** in an `asyncio.TaskGroup`: each `create_task` is the `run` of a complete package, with its own Container. No generic phase executor nor list of callbacks — the group stays visible in the parent's `run`, and each branch is a process that reads on its own.

The same holds for **fan-out over items**: N calls of a sibling package's `run`, each with its own Container. Real example from the template, `backend_logic/roles/digest/run.py` (one summary per note, tested in `tests/example/test_roles_digest.py`):

```python
async def run(initial: DigestNotes, *, model: Model) -> Digest:
    pipe = (
        Pipe
            .get(initial)
                .validate_notes(max_notes=8)
                    .prepare_requests()
    )
    if pipe.container.requests is None:
        raise RuntimeError("digest requires prepared requests before the parallel calls")
    # Failure policy: TaskGroup. The first rejected summary cancels the calls still running
    # and the whole digest fails as an ExceptionGroup; a partial digest is never returned.
    async with asyncio.TaskGroup() as group:
        tasks = [
            group.create_task(summarizing.run(request, model=model))
            for request in pipe.container.requests
        ]
    # After the barrier, in request order: the digest never depends on which call finished first.
    return (
        pipe
            .integrate_summaries(tuple(task.result() for task in tasks))
                .materialize()
    )
```

The budget (`max_notes=8`) is validated before any paid call; a duplicate note is rejected, not deduplicated. The test proves real concurrency: the fake only answers the first note after the second finishes, so a sequential version would hang and blow the `asyncio.timeout`. The digest comes out in the order of the notes, not in completion order. A rejection cancels the pending calls, and the caller handles the `ExceptionGroup` with `except*`.

With **different** branches, the skeleton is the same, one task per branch:

Aligning operations communicates branches of the same parallel group **only** when the execution really schedules them that way. Whitespace does not create concurrency.

```python
lazy from .images import run as images
lazy from .optional import run as optional
lazy from .thumbnail import run as thumbnail


async def prepare_optional(source: Source) -> Optional:  # sequential branch inside the group
    downloaded = await optional.run(source)
    return await thumbnail.run(downloaded)


async with asyncio.TaskGroup() as group:
    optional_task = group.create_task(prepare_optional(source))
    images_task = group.create_task(images.run(source))
# Integration after the barrier, in fixed order — not in completion order.
pipe.container.optional = optional_task.result()
pipe.container.images = images_task.result()
```

- The children receive explicit inputs and return outputs; only the parent writes to its Container, and only after the barrier.
- Independence is semantic, not just different fields. Exclusive writes are allowed; two writers on the same canonical state, no.
- Integrate results deterministically, not in completion order.
- Cancellation does not undo external effects nor become success.
- `TaskGroup`, `gather` and variants have different failure policies: choose and declare.

### 4.5. `materialize`

Closes the process. It may execute explicitly deferred work when that is the contract, but the name does not prove that nothing happened before nor authorize a hidden effect queue. Repeating `materialize` is not automatically safe: declare single consumption when there is paid inference or commit.

---

## 5. Container

- The constructor really creates `self.container = Container()`, with declared empty fields. No `dict`, `SimpleNamespace`, `kwargs` or dynamic attributes.
- Fixed shape; progressive values. **Initial `None` is legitimate, not mandatory**: accumulators and phases use a typed empty (`attempt_count: int = 0`, `refresh_used: bool = False`, `authorizations: tuple[...] = ()`, `scope: Scope = "prepare"`). Each method declares what it reads, requires, writes and preserves.
- `get(initial)` may do the declared initial preparation — copy/detach the input (`deepcopy`), initialize accumulators — but does not hide global loading.
- A missing required field fails **explicitly** (`if x is None: raise RuntimeError(...)`), never with `assert` — `python -O` removes asserts.
- No invented defaults. If `None` is also a valid output, distinguish it from "step not executed" with a type of its own (`AvatarSelection(value=None)`, `Literal[True] | None`).
- One `Pipe`/`Container` instance per invocation. Never share request state between calls.
- `materialize` does not expose the container. A Container is not a public DTO, prompt nor persisted schema.

---

## 6. Strict typing

The goal is not green mypy: it is to **reduce what the implementer has to guess**.

- Forbidden: `Any`, unparameterized collections (`dict`, `list`), untyped imports treated as `Any`, `cast`/`# type: ignore` to hide an incomplete contract.
- Do not swap `Any` for `object`/`dict[str, object]`/`JsonValue` across the whole domain just to pass the rule.
- Use dataclass, `TypedDict`, `Protocol`, discriminated unions, `Literal`, `Enum`, `NewType` when they express real distinctions.
- Known finite choices are `Literal`/`Enum`, not `str`.
  In the template: error codes shown to the client (`NoteConflictCode`, `NoteValidationCode`), the atomic write phase (`WritePhase`) and the role's language (`Language`). A new code becomes a contract change visible in the type, and not a string someone invented in a `raise`.
- A number with its own role is `NewType`, not `int`: `Revision` is not swapped for `schema_version`, for a count nor for a size. The step that admits the value is the one that constructs it (`Revision(current.revision + 1)`); a test that needs a value writes it explicitly (`Revision(1)`).
- Distinguish what cannot be confused: identity vs reference, proposal vs admitted fact, raw document vs validated object, absence vs step not executed, result vs effect receipt.
- `dict` is legitimate for dynamic keys, with typed key and value. A record of known fields declares the fields.
- **Untrusted data is wide only at the ingestion boundary** (recursively typed JSON, `bytes`). Admission produces specific types; indeterminacy does not cross the packages. A library API that returns `Any` gets a containment boundary.
- The strength of the type corresponds to the step's knowledge: input still subject to rejection is not annotated as admitted.
- Types do not prove ranges, relations between fields, privacy or temporal order: declare preconditions and validate at runtime.
- Never relax the gate (exclude a module, turn off a rule) to get green.

Reference configuration (the template's `pyproject.toml`): `mypy strict = true`, `disallow_any_explicit`, `disallow_any_unimported`, **global** `disallow_any_expr` (logic, HTTP adapter and tests), `warn_unreachable`, `strict_bytes` and the extra codes `ignore-without-code`, `redundant-expr`, `redundant-self`, `truthy-bool`, `truthy-iterable`, `possibly-undefined`, `unused-awaitable`, `explicit-override`, `mutable-override`, `exhaustive-match` and `deprecated`; Ruff with `E,F,I,N,W,UP,B,C4,SIM`. The test `tests/gates/test_config.py` fails if this configuration is loosened.

**`Any` only as a last resort, and contained.** When a library hands over `Any` with no typed alternative, it stays trapped in a boundary module with its own name, which narrows the value (`isinstance`, strict decoding) before returning it. Only those modules are exempt from `disallow_any_expr` in `pyproject.toml`. The template has three, explained in [template-decisions.md](template-decisions.md) (C2); a new boundary in the project requires an owner decision and an entry in `architecture-log.md`:

| Boundary | `Any` from whom | Comes out as |
| --- | --- | --- |
| `backend_logic/_shared/json/decode` | `json.loads` and its hooks | `JsonValue` |
| `tests/gates/test_config.py` | `tomllib.loads` | values narrowed by `isinstance` |
| `tests/support/wire_client.py` | Starlette's `TestClient` (reaches mypy entirely as `Any`) | `WireResponse(status: int, body: JsonValue)` |

Before opening a boundary, look for the typed way out. In the template these were:

- **FastAPI decorators** (`@router.get`) are typed with `Any`: routes are registered with `router.add_api_route(path, function, methods=[...])`.
- **A library `Any` parameter** (`JSONResponse(content)`, `json.dumps(obj)`): pass an already annotated value (`body: JsonValue = {...}`) so the literal is not inferred with `Any`.
- **Overriding in fakes:** `@override` on every redefined method. Extra data of the fake lives in an attribute of the fake, not in a subclass of the Container, because narrowing an inherited mutable attribute is unsafe (`mutable-override`).
- **Purposely wrong call** in a runtime guard test: `# type: ignore[call-overload, misc]`, always with code and comment. They are the template's only `ignore`s, both in `tests/example/test_backend_run.py`.

**Review of raw `str`/`int` (what does not become its own type).** Input still subject to rejection stays `str` (`SaveNote.name`, the storage's `relative`s): whoever admits it is `_shared/note_name` or `storage/_shared/path`, and annotating before that would lie. Free text (`body`, prompt, `ModelReply.content`) stays `str`. Call budgets stay `int` with a name on the parameter (convention in `vocabulary.md`).

### 6.1. `lazy` imports (Python 3.15, PEP 810)

The template requires Python 3.15 for one reason: `lazy import`. **Every top-level module import in `backend_logic` and `http_adapter` is `lazy`**:

```python
lazy import asyncio
lazy from typing import Self

lazy from backend_logic.roles.summarizer import run as summarizing
lazy from .container import Container
```

The module is only loaded on first use of the name. Importing `backend_logic.run` does not load `storage/write` nor `roles/digest` until a request passes through them, so startup loads only the path it uses. The package tree can grow without each `contracts.py` pulling in the whole project.

Language rules:

- `lazy` only applies at the top of the module. An import inside a function, class or `try` stays normal, and the gate does not charge it.
- `from __future__ import ...` and `import *` cannot be lazy.
- **The error changes place.** A missing module, or an import side effect, only shows up on first use, not when opening the file. That is why the tests that exercise each path (the real `run` of each package) are what guarantees the imports resolve.

**Fallback:** if a package does not work as lazy (registration at import time, a side effect the code depends on, a tool that does not yet understand the syntax), replace the `lazy import` with a normal `import` at that point. The behaviour is the same, only eager. For the gate to accept the swap:

1. register the module in `EAGER_IMPORTS` (in `tests/gates/test_style.py`) with the reason;
2. record the exception in `architecture-log.md`.

To return the whole project to eager, remove every `lazy `. The template was verified this way: same tests green and mypy clean. In this CPython build, `-X lazy_imports` accepts only `all` and `normal` and does not turn off explicit lazy, so the fallback is to change the code, not to pass a flag.

Gate: `tests/gates/test_style.py::test_every_top_level_import_is_lazy`.

---

## 7. Parents, children and sharing

- A package is a complete vertical process and may nest as much as is useful. Avoid a god-package to "keep the sequence together".
- The parent passes **explicit inputs** and integrates the children's **outputs**. It does not hand its whole Container to each child. Read-only references and bounded access to a draft are allowed.
- Descending to the child to see details is desired; hunting for the parent's continuation in scattered callbacks and dispatchers is not.
- **Helpers are local by default** (§2: depth says who shares). One consumer: stays local, at maximum depth. Two siblings really needing it: move up to the common parent, beside them, not to the root. Two uses are a necessary condition to share, **not an obligation**. Simple duplication may read better — except authoritative policy (below).
- Imagined uses do not justify abstraction. But a single authoritative policy (privacy, validation, commit, retry) is not duplicated.
- New packages may be moved, split or replaced — updating producers, consumers, imports and tests **together**. New code is not legacy: no compatibility wrappers, double parsers or aliases.

---

## 8. Literals, parameters and configuration

- A fixed local choice is a literal at the call site: `.prepare_request(output_tokens=384, response_mode="structured")`. Do not mechanically promote it to a module constant, Settings or env.
- A parameter may exist even when the value "could be fetched inside": it makes the origin visible and the transformation reproducible in a test.

  ```python
  pipe.prepare_prompt(language="pt-BR")  # fixed local decision
  pipe.prepare_prompt(language=parent.container.language)  # comes from the parent
  ```

- Real user/session/environment/credential values are **not** literals. The initial composition that owns them loads once and passes explicitly. Children do not consult env/config on their own.
- **A global package is not a global variable.** A shared LLM dispatcher receives client/config by argument; there is no singleton imported by everyone.
- "Load once and pass" does not mean a megacontainer passed whole to everyone.

---

## 9. Effects, commit and receipts

- External effects (write, network, paid inference) happen in methods whose name and docstring declare them, with a domain name when they are not canonical publication (e.g. `open_response`, `capture_response`, `publish_checkpoint`). `commit` is reserved for "publish a canonical change with a receipt".
- `commit` publishes once, keeps a `*Receipt` in the Container and propagates the failure without hidden retry. The receipt records the real state: `NOT_PUBLISHED` (target not replaced — **not** "no effect": parent directories may have been created), `PUBLISHED_NOT_DURABLE` (bytes visible, crash durability not confirmed; never treat as rollback), `DURABLE`.
- Durable write: temporary file in the same directory → flush → fsync → atomic replace (the template brings `storage/write/`, called by `writing.run(WriteDocument(...))`).
- **Never offload a write to a thread (`asyncio.to_thread`) under an async lock**: cancelling the coroutine releases the lock, but does not stop the filesystem effect.
- Mutate isolated drafts; advance the canonical revision once.
- **Distinguish pre-commit failure from post-commit failure.** A failure in the publication itself propagates the write error with its receipt (`AtomicWriteError.receipt`); a failure **after** the publication (assembling the result, observer, presentation) becomes `*ResultError` carrying the receipt. In both cases, never regenerate persisted work. Discarding a draft does not undo an external effect.
- Resources (config, client, store, locks) have **one explicit owner** with declared lifetime. No parallel caches becoming authority.
- Every operation on a shared resource (including reads) uses the owner's lock. Reentrancy is an **explicit per-resource decision**. E.g.: the template's named locks (`storage/lock`) are non-reentrant `asyncio.Lock`s: the parent's `run` acquires, the child declares in the docstring "requires lock already held", and a child that reacquires the same lock is a bug (deadlock). A configuration lock shared by load/update/save may be a reentrant `RLock`, if the owner decides and records it.
- Several locks: documented fixed acquisition order (e.g. entities in lexical ID order, then named locks by `(kind, name)`), release in reverse order.
- **Never evict locks** from the registry when deleting a record: a waiter or retained reference could overlap a new lock. The registry grows with the valid names; limit the names in validation, not by removing locks.

---

## 10. Two applications and dependency direction

| `backend_logic` | `http_adapter` |
| --- | --- |
| Domain, agents, pipelines, validation, transactions, persistence, provider/plugin abstractions. | HTTP routes, request/response encoding, status/errors/SSE, assets, transport security. |
| **Never** imports FastAPI, Starlette, pydantic, transport DTOs or `http_adapter`. | Enters **only** through `backend_logic/run.py` (`from backend_logic import run as backend`) and imports from the logic only `contracts` modules (the types of requests and products). Never imports a family's `run`, `pipeline`, `container` or `helpers`. Resources (store, locks, clock) are prepared in the `lifespan` by `backend.run(PrepareResources(...))` and kept in a local adapter slot (`ResourceSlot`); `tests/gates/test_architecture.py` guarantees the single door. |

Style rule: **do not blindly impose the style's details on the HTTP framework**. The HTTP adapter's hard rules are dependency direction and not duplicating business; names such as `create_app`/`build_router` are HTTP framework idiom, not a violation of the pipelines vocabulary.

Decoding the HTTP body is also an ingestion boundary. **This template's choice** (the style itself does not require it): read bytes, pass through the same strict JSON of the logic (`_shared/json/decode`) through the single door (`backend.run(DecodeText(...))`: duplicates, NaN, surrogates, depth) and check the wire shape in a dataclass, responding with `JSONResponse`. The template avoids pydantic because its models introduce `Any` and the global `disallow_any_explicit` would fail. If the owner prefers pydantic at the edge, record the decision and the gate adjustment in `architecture-log.md`; in `backend_logic`, never.

HTTP handlers do not resolve domain defaults, do not mutate state, do not apply visibility rules and do not duplicate business rules: that is a logical use case with its own `run`.

The template's `tests/gates/test_architecture.py` guarantees by AST: dependency direction, `run.py` with a real `run` and package imports without network/opening of data.

---

## 11. LLM agents

Patterns for any project with model roles:

- **Roles are provider-neutral.** A role (`roles/<role>/`) assembles context, asks for a call to a port (`Protocol`) and admits the response. Provider differences live in adapters (`llm/providers/<provider>/`).
- **Privacy before context.** What the model may not know does not enter the prompt. Never "ask the model to forget". Declare in `AGENTS.md` what each role may know (e.g.: "internal IDs do not reach the prompt" is one domain's invariant; another product may need IDs in the prompt).
- **Proposal ≠ fact.** The model's output is a `*Candidate`/`Proposed*`; it becomes state only after `admit_*` under the domain's authority, and only then `commit`.
- **Structured output with mandatory contract and local validation.** An unsupported schema feature fails instead of vanishing.
- **One logical call owns its retries.** Explicit budget, backoff in `run`, receipts/evidence before and after the dispatch. An evidence/observer error does not authorize replaying the generation.
- **Private, sanitized evidence**, keyed by your domain's identities (e.g. `session_id`, `turn_number`, `agent`); secrets never in logs, URLs, CLI arguments or chat. **Sanitizing does not declassify**: what is a domain secret remains a secret after being sanitized; raw streaming fragments can reconstruct secrets.
- **Capture the complete binding (provider, model, config, client) before waiting for a lock**, so that a concurrent configuration swap does not alter an in-flight operation.
- **Per-request isolation in the shared HTTP client**: direct requests do not inherit the client's headers, params or cookie jar; auth flows and redirects turned off; the exchange closes its response, not the owner's client.
- **A single credential-recovery budget**, separate from the generation retries and shared by all attempts (e.g.: 401 may renew once; 403 never renews).
- **Context budgets in tokens**, not arbitrary truncation by characters. If only a heuristic exists (`chars/4`), call it an estimate, not a tokenizer.
- If the product has a shape contract for generated text (e.g. prose punctuation), normalize in one central place, on the selected fields, never over identifiers/URLs.
- **Mocks are the default.** A real model/network/OAuth call requires explicit and finite authorization; credentials being present is not authorization. Real tests stay under a marker (`-m llm`) turned off by default.

---

## 12. Process: write, type, rehearse, only then fill in

### 12.1. Sequence

1. Survey capabilities, inputs/outputs, authorities and effects (from the sources, the product, the owner).
2. Write **real** contracts and compositions in the code.
3. Verify typing, imports and links.
4. **Rehearse the runs with typed fakes**, including pertinent failures.
5. Fix the gaps/contradictions revealed.
6. Walkthrough with the owner, if the authorization requires it.
7. Only then delegate the filling in of methods or cohesive sets.

Logic not yet implemented stays explicit:

```python
def prepare_prompt(self, *, language: str) -> Self:
    """Read input; set prompt; no I/O and no other field changes."""
    raise NotImplementedError("summarizer.prepare_prompt")
```

Never return an empty success to pretend it works. `pass` in a function with a return can hide an invalid return. Mocks stay in tests, never as a production fallback.

### 12.2. The cycle and the return to the skeleton

**Survey → write/readjust contracts and compositions → rehearse → implement/delegate → integrate → confront again with the sources.**

After integrating, decide:

- **Few local gaps** (capability and authority already represented): fix directly and check consumers.
- **Numerous or coupled structural absences** (missing processes, ownership, transactions, links): go back to the design in code, widen and readjust what already exists, rehearse, and only then another wave.

A repeated typing error can denounce a wrong type, a missing authority or a package in the wrong place. Do not accumulate conversions, parameters and methods to turn the gate green. Also do not redesign everything over a typo.

### 12.3. Rehearsal (skeleton simulation)

- **Typed** fakes that respect the signature and fill in fields coherent with the pre/postconditions. No permissive mocks that accept any attribute.
- Exercise **real runs**, swapping only unimplemented leaves/boundaries — without rewriting the orchestration inside the test.
- Meaningful data crossing packages; verify preserved/changed fields, order, handoffs, branches, failures, cancellation.
- A fake that returns a constant disconnected from the input makes the test vacuously green.
- A concurrency test without `await` inside the critical section does not observe the lock: rehearse the lock with a holder that waits inside it (see `tests/example/test_notes_save.py`). Guards also need a test: an import scanner that only read `node.module` passed empty.
- Show cases the contract rejects when that clarifies a distinction, including **proportional negative static checks** (swapping nominal IDs/stages must fail in mypy). Do not leave purposely invalid fixtures mixed into production code.
- Copy/snapshot semantics need to be rehearsed at runtime: a name, type or `Self` neither freezes objects nor guarantees a copy.
- **Record which links were simulated**, with what premises and which were not yet. The record cannot be verified only against itself.
- **Code and test can share the same wrong interpretation.** Confront with real sources and consumers. Fix the wrong fixture; do not loosen the correct implementation.

### 12.4. Tests per package or stretch

- The natural boundary is the package/segment: known input, output, sequence and effects. Select by risk and doubt, not a per-method quota.
- Mock only the child outside the investigation.
- **Start in the middle:** prepare a valid Container at that step and execute only the suspect stretch. Never a state that the real pipeline would not produce.

```python
pipe = Pipe.get(ListNotes())
pipe.container.files = ("b.json", "a.txt")  # real state right after scan_directory

listed = pipe.select_stems(suffix=".json").admit_names().sort_names().materialize()
```

- Default tests use a temporary data directory, mocked providers and synthetic fixtures. Real data is never a fixture.

---

## 13. Coordinator as architect; delegated work

The coordinator (the **orchestrator model**, a frontier model) is the **architect**, not the default developer of all the leaves: it owns the global survey, contracts, compositions, rehearsal and integration. It may fix a small local gap; with many gaps, it recovers the design and prepares another wave. The session's subagents, on intermediate or smaller models, fill in only method bodies. The step-by-step of the waves, the delegation package template and the report format are in [construction.md](construction.md).

**Delegation package** (what each implementer agent receives):

- Signature, types, inputs/outputs, dependencies.
- Container fields read, required, written and preserved.
- Allowed/forbidden effects, failures, cancellation, invariants.
- Fixtures/rehearsals and oracles of the stretch.
- **Files under its exclusive ownership**, without permission to redesign consumed contracts.

The agent does not rebuild the system to discover the contract. If information is missing or the contract is impossible, it **reports the gap** to the coordinator instead of inventing. No simultaneous editing of the same file. No recursive delegation, unless the owner decides otherwise.

**Before judging the result of a wave, classify the absence:**

1. Implementation error — contract and link existed; the leaf did not fulfil it.
2. Architectural error/omission — insufficient contract or missing consuming composition.
3. Undistributed capability — was never in the delivered scopes.

Redistributing a method solves (1); it does not invent the authority of (2) nor conclude (3).

Number of agents, passing tests and percentages are **not** evidence of completion or quality. A hit-rate gain from a precise contract is a hypothesis to measure, not a promise.

---

## 14. Honest documentation

- **Package README** (when the package has relevant decisions): what it is, what it is **not**, inputs/responsibilities, explicit corrections relative to the source, and what is missing. E.g.: "This is a projected context, **not** a complete prompt."
- **Vocabulary** (`docs/design/vocabulary.md`): names defined by the owner and proposals under observation, with the limit of each one.
- **Architecture log** ([`architecture-log.md`](architecture-log.md), of the new project, born empty), per decision: observation and source → state (absent/rehearsed/implemented/integrated/verified) → diagnosis (1/2/3 above) → decision and reason → evidence needed and what it will **not** prove → later result.
- The log points to the code; it does not become a parallel tree that looks finished. Historical documents are not rewritten to pretend past coverage.
- When reporting: "X rehearsals with finite leaves and N real cases demonstrate these handoffs, **not** Y". Never "it works" without evidence from the real component.

---

## 15. Data, secrets and experiments

- Real data and copies are private, ignored by git and never fixtures.
- Never print configs/tokens nor put them in versioned files, browser storage, URLs, arguments or chat.
- A change of persisted representation requires a schema version and an explicit decision: authorized migration or clear rejection. No double parsers nor legacy defaults.
- Drafts/scratch in `.dumps/` (ignored).
- Network, paid model, OAuth, commit, push and publication require explicit authorization.

---

## 16. Anti-patterns

| Symptom | Why it is wrong | Do |
| --- | --- | --- |
| `self.result`, `self.ctx`, `have()`, `build()` | Splits the vocabulary | `self.container`, `get`, `materialize` |
| `def x(self) -> Self: pass` | Pretends success | `raise NotImplementedError("package.method")` |
| `assert self.container.x` | Vanishes with `-O` | `if ... is None: raise RuntimeError(...)` |
| `MAX_TOKENS = 384` at the top, used once | False configuration | literal at the call site |
| `from app.settings import SETTINGS` inside a child | Global state | pass explicitly from the owner |
| `dict[str, Any]` crossing the domain | Hides the contract | declared fields; JSON only at ingestion |
| Step engine/phase registry | Hides the order | fixed order in `run` |
| Parent hands its whole Container to the child | Diffuse coupling | explicit inputs |
| `helpers/` with a single consumer's function | Premature abstraction | keep it local |
| Compatibility wrapper for new code | Keeps two truths | migrate consumers together |
| HTTP handler applying a business rule | Logic outside the owner | new logical `run` |
| Mock that accepts any attribute | Vacuously green test | coherent typed fake |
| Retry after the commit because the log failed | Duplicates the effect | `*ResultError` with receipt |
| `asyncio.to_thread(writing.run, WriteDocument(...))` under lock | Cancellation releases the lock with the write still running | synchronous write inside the lock |
| Loose module (`files.py`, `jsonvalue.py`, `utils.py`) | Reader does not know where to start nor what it is | package per operation with the five files |
| HTTP adapter calling `notes.run` or `storage` directly | Side door; the climb disappears | `backend_logic/run.py` + `contracts` |
| `validate_*` that does `.strip()` | Fixes instead of checking | reject, or a named normalization step |
| "Tests green, it's done" | Confuses mechanics with product | report what was and was not proven |

---

## 17. Checklist

- [ ] Is the project navigable by real files, types and calls before the logic?
- [ ] Does every folder have the five files and no other? Does every use case descend from `backend_logic/run.py` by `match` down to the leaf?
- [ ] Does each `run` show its story without flattening that of the children?
- [ ] Consistent vocabulary; new names recorded as a proposal?
- [ ] Container with declared empties in the constructor (`None` or typed empty), precise fields, intermediates only in it?
- [ ] No domain knowledge hidden in `Any`, vague collections or casts?
- [ ] Do types distinguish real alternatives; do preconditions cover what types do not prove?
- [ ] Do literals/parameters show decisions and origins, without globals nor megacontainer?
- [ ] Does sharing have real consumers and improve the reading? Does each package live at the nearest common ancestor of its consumers?
- [ ] Is parallel a `TaskGroup` of sibling `run`s, integrated in fixed order after the barrier?
- [ ] Do indentation, awaits, effects and barriers tell the same story?
- [ ] Runs rehearsed with typed fakes and coherent data between packages?
- [ ] Can I isolate a stretch by preparing a valid intermediate Container?
- [ ] Does an agent understand its method without inventing architecture?
- [ ] Is the gap local or does it require readjusting the skeleton?
- [ ] Producers and consumers reorganized together, without wrapper?
- [ ] Pre-commit and post-commit failure distinguished, with receipt?
- [ ] Did I not confuse typing/simulation with a finished product, nor hypothesis with measured gain?

---

## 18. What each new project decides (does not come ready-made)

The template brings the form; these choices belong to each project's owner, written in the `FILL IN` sections of `AGENTS.md` and recorded in `architecture-log.md` when they change something of the template:

- **Domain invariants:** what each role may know, who has authority over which result, what never enters a prompt. The form is fixed (list in `AGENTS.md`, applied by projection before the context, §11); the content belongs to the domain.
- **Domain identities:** the evidence and lock keys (`session_id`, `turn_number`…) and which IDs may appear in the prompt.
- **Provider and model per role**, and where the adapters live.
- **Critics and delegation policy:** whether reviews by critic subagents are on, how many agents per wave, whether there is recursive delegation. A large number of agents is a one-off authorization, not a quota.
- **Reconstruction profile**, only if the project rebuilds an existing app: private snapshot in `.dumps/` (never importable), parity by differential simulations, preserved route inventory.
- **Top-level names** (`backend_logic`/`http_adapter`) and the Python version: keep them if they make sense; changing is a recorded decision (3.15 exists because of `lazy import`, §6.1).

The example domain (`notes`, `roles/summarizer`, `roles/digest`) exists to show the form: replace it with the real domain while keeping the mechanisms (`_shared/json/*`, `notes/_shared/storage/*`, the resources of `notes/prepare`) and the style, architecture and configuration tests. When replacing the domain, the mechanisms **change place** according to real use: if only one domain writes to disk, `storage/` goes to its `_shared/`, together with the resources' `prepare/`; if two domains write, `storage/` moves up to `backend_logic/_shared/`. The `test_style.py` gate points out the wrong place.

`endpoint`/`have`/`arun` are historical names from old versions of the style, not conventions.

**Summary: write, type and rehearse the project in Python; review its boundaries; only then fill in the transformations. Go back to the skeleton when the gaps are structural. The code is the blueprint, not a promise of a future blueprint.**