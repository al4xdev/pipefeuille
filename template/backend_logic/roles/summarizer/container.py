lazy from dataclasses import dataclass

lazy from .contracts import (
    ModelReply,
    ModelRequest,
    NoteView,
    ProposedSummary,
    SummarizeNote,
    Summary,
)


@dataclass
class Container:
    input: SummarizeNote | None = None
    view: NoteView | None = None
    system: str | None = None
    user: str | None = None
    request: ModelRequest | None = None
    reply: ModelReply | None = None
    proposal: ProposedSummary | None = None
    summary: Summary | None = None
