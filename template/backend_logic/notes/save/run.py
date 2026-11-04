lazy from backend_logic.storage import run as storing
lazy from backend_logic.storage.lock.contracts import LockRegistry, SelectLock
lazy from backend_logic.storage.path.contracts import FileStore

lazy from .contracts import Clock, NoteResultError, SavedNote, SaveNote
lazy from .pipeline import Pipe


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
    async with storing.run(SelectLock(locks, kind="note", name=pipe.container.name)):
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
