lazy from dataclasses import dataclass

lazy from backend_logic.notes.save.contracts import NoteRecord
lazy from backend_logic.roles.summarizer.contracts import Language, Summary


@dataclass(frozen=True)
class DigestNotes:
    """Several notes to summarize in one language; each one costs a model call."""

    notes: tuple[NoteRecord, ...]
    language: Language


@dataclass(frozen=True)
class Digest:
    """One admitted summary per note, in the order the notes were given."""

    summaries: tuple[Summary, ...]


class DigestRejectedError(ValueError):
    """The request itself is outside the contract; no model call was made."""
