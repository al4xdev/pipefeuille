lazy from typing import Self

lazy from backend_logic.storage.lock.contracts import LockRegistry
lazy from backend_logic.storage.path.contracts import FileStore

lazy from .container import Container
lazy from .contracts import NotesRequest, NotesResponse
lazy from .list import run as listing
lazy from .list.contracts import ListNotes
lazy from .save import run as saving
lazy from .save.contracts import Clock, SaveNote


class Pipe:
    def __init__(self) -> None:
        self.container = Container()

    @classmethod
    def get(cls, initial: NotesRequest) -> Self:
        """Set input unchanged; run chooses the branch."""
        pipe = cls()
        pipe.container.input = initial
        return pipe

    def list_notes(self, request: ListNotes, *, store: FileStore) -> Self:
        """Set listed through the list child. Read-only; a misnamed file fails it."""
        self.container.listed = listing.run(request, store=store)
        return self

    async def save_note(
        self, request: SaveNote, *, store: FileStore, locks: LockRegistry, clock: Clock
    ) -> Self:
        """Set saved through the save child, which owns its lock, commit and receipt."""
        self.container.saved = await saving.run(request, store=store, locks=locks, clock=clock)
        return self

    def materialize(self) -> NotesResponse:
        """Require exactly the branch that ran; return its product."""
        if self.container.listed is not None:
            return self.container.listed
        if self.container.saved is not None:
            return self.container.saved
        raise RuntimeError("a notes branch must run before materialize")
