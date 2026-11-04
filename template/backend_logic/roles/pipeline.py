lazy from typing import Self

lazy from .container import Container
lazy from .contracts import RolesRequest, RolesResponse
lazy from .digest import run as digesting
lazy from .digest.contracts import DigestNotes
lazy from .summarizer import run as summarizing
lazy from .summarizer.contracts import Model, SummarizeNote


class Pipe:
    def __init__(self) -> None:
        self.container = Container()

    @classmethod
    def get(cls, initial: RolesRequest) -> Self:
        """Set input unchanged; run chooses the branch."""
        pipe = cls()
        pipe.container.input = initial
        return pipe

    async def summarize_note(self, request: SummarizeNote, *, model: Model) -> Self:
        """Set response through the summarizer child: one model call, never repeated here."""
        self.container.response = await summarizing.run(request, model=model)
        return self

    async def digest_notes(self, request: DigestNotes, *, model: Model) -> Self:
        """Set response through the digest child: one model call per note, in parallel."""
        self.container.response = await digesting.run(request, model=model)
        return self

    def materialize(self) -> RolesResponse:
        """Require response; return it."""
        if self.container.response is None:
            raise RuntimeError("a roles branch must run before materialize")
        return self.container.response
