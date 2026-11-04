lazy from dataclasses import dataclass
lazy from typing import Literal, Protocol

lazy from backend_logic.notes.name.contracts import NoteName
lazy from backend_logic.notes.save.contracts import NoteRecord


@dataclass(frozen=True)
class ModelRequest:
    """Provider-neutral request; adapters translate it to their wire format."""

    system: str
    user: str
    output_tokens: int
    response_mode: Literal["text", "structured"]


@dataclass(frozen=True)
class ModelReply:
    """Raw provider content: not normalized, parsed or admitted."""

    content: str


class Model(Protocol):
    """One logical call. The implementation owns its retries and evidence; callers do not."""

    async def complete(self, request: ModelRequest) -> ModelReply: ...


# Closed set: the prompt is written and evaluated per language, so adding one is a decision.
type Language = Literal["en", "pt-BR"]


@dataclass(frozen=True)
class SummarizeNote:
    """One note to summarize; the role projects it before any prompt text exists."""

    note: NoteRecord
    language: Language


@dataclass(frozen=True)
class NoteView:
    """Model-facing projection. Contains no internal IDs or routing fields."""

    title: NoteName
    body: str


@dataclass(frozen=True)
class ProposedSummary:
    """Decoded model output, still subject to admission."""

    sentences: tuple[str, ...]


@dataclass(frozen=True)
class Summary:
    """Admitted summary: nonblank sentences within the declared limit."""

    sentences: tuple[str, ...]


class SummaryRejectedError(ValueError):
    """The reply violated the contract; the caller decides whether a new call is authorized."""
