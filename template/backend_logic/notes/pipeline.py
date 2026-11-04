lazy from typing import Self

lazy from .container import Container
lazy from .contracts import NotesRequest, NotesResponse
lazy from .list import run as listing
lazy from .list.contracts import ListNotes
lazy from .prepare import run as preparing
lazy from .prepare.contracts import PrepareResources, Resources
lazy from .save import run as saving
lazy from .save.contracts import SaveNote


class Pipe:
    def __init__(self) -> None:
        self.container = Container()

    @classmethod
    def get(cls, initial: NotesRequest) -> Self:
        """Set input unchanged; run chooses the branch."""
        pipe = cls()
        pipe.container.input = initial
        return pipe

    def prepare_resources(self, request: PrepareResources) -> Self:
        """Set prepared through the prepare child. Called once per application lifetime."""
        self.container.prepared = preparing.run(request)
        return self

    def list_notes(self, request: ListNotes, *, resources: Resources) -> Self:
        """Set listed through the list child. Read-only; a misnamed file fails it."""
        self.container.listed = listing.run(request, store=resources.store)
        return self

    async def save_note(self, request: SaveNote, *, resources: Resources) -> Self:
        """Set saved through the save child, which owns its lock, commit and receipt."""
        self.container.saved = await saving.run(
            request, store=resources.store, locks=resources.locks, clock=resources.clock
        )
        return self

    def materialize(self) -> NotesResponse:
        """Require exactly the branch that ran; return its product."""
        if self.container.prepared is not None:
            return self.container.prepared
        if self.container.listed is not None:
            return self.container.listed
        if self.container.saved is not None:
            return self.container.saved
        raise RuntimeError("a notes branch must run before materialize")
