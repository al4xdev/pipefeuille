lazy from backend_logic.notes._shared.storage.contracts import FileStore
lazy from backend_logic.notes._shared.storage.lock import run as locking
lazy from backend_logic.notes._shared.storage.lock.contracts import LockRegistry, SelectLock

lazy from .contracts import Clock, NoteResultError, SavedNote, SaveNote
lazy from .pipeline import Pipe


async def run(
    initial: SaveNote, *, store: FileStore, locks: LockRegistry, clock: Clock
) -> SavedNote:
    """Create or replace a note under its named lock.

    Effects:
        reads: the current note, to admit creation or replacement.
        writes: the note file, published once by commit.
        time: the record timestamp, from the clock port.
    Repeat:
        fails: a second create of the same name conflicts; a stale revision conflicts.
    Loops:
        none
    Concurrency:
        locks-inside: the note's named lock, across read, admission and commit.
    Raises:
        NoteValidationError: the name breaks the note-name grammar; nothing was read.
        NoteConflictError: note_exists, note_missing or revision_conflict; nothing was written.
        AtomicWriteError: publication failed; carries the receipt of what reached the disk.
        NoteResultError: failure after commit; carries the receipt, the note is published.
        ValueError: the stored predecessor is corrupt or misfiled.
    """
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
