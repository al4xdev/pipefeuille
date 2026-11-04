lazy from typing import assert_never, overload

lazy from backend_logic.storage.lock.contracts import LockRegistry
lazy from backend_logic.storage.path.contracts import FileStore

lazy from .contracts import NotesRequest, NotesResponse
lazy from .list.contracts import ListNotes, NoteNames
lazy from .pipeline import Pipe
lazy from .save.contracts import Clock, SavedNote, SaveNote


@overload
async def run(
    initial: ListNotes, *, store: FileStore, locks: LockRegistry, clock: Clock
) -> NoteNames: ...
@overload
async def run(
    initial: SaveNote, *, store: FileStore, locks: LockRegistry, clock: Clock
) -> SavedNote: ...
async def run(
    initial: NotesRequest, *, store: FileStore, locks: LockRegistry, clock: Clock
) -> NotesResponse:
    pipe = Pipe.get(initial)
    match initial:
        case ListNotes():
            pipe.list_notes(initial, store=store)
        case SaveNote():
            await pipe.save_note(initial, store=store, locks=locks, clock=clock)
        case _:
            assert_never(initial)
    return pipe.materialize()
