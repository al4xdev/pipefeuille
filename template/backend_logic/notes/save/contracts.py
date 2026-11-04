lazy from dataclasses import dataclass
lazy from datetime import datetime
lazy from typing import Literal, NewType, Protocol

lazy from backend_logic.storage.write.contracts import PublicationStatus, WriteReceipt

lazy from ..name.contracts import NoteName

# Nominal identity: server-side routing, never prompt text nor client input.
AuthorId = NewType("AuthorId", str)
# Nominal: a revision is not a count, a schema version nor a size. Constructing one
# validates nothing; save admits it (1 on creation, current + 1 on replacement).
Revision = NewType("Revision", int)

# Closed set: the frontend shows these to clients, so a new code is a contract change.
type NoteConflictCode = Literal["note_exists", "note_missing", "revision_conflict"]


@dataclass(frozen=True)
class NoteRecord:
    """Canonical persisted note: what save publishes and every reader admits."""

    schema_version: Literal[1]
    name: NoteName
    body: str
    author_id: AuthorId
    revision: Revision
    updated_at: datetime


class Clock(Protocol):
    """Caller-owned time source; returns an aware UTC instant, sampled under the note lock."""

    def now(self) -> datetime: ...


@dataclass(frozen=True)
class SaveNote:
    """Candidate submission. author_id comes from the server-side caller, never the body."""

    name: str
    body: str
    author_id: AuthorId
    replace: bool
    expected_revision: Revision | None


@dataclass(frozen=True)
class CurrentRead:
    """Completed lookup; record=None is observed absence, not a lookup not yet run."""

    record: NoteRecord | None


@dataclass(frozen=True)
class SavedNote:
    record: NoteRecord
    publication: Literal[PublicationStatus.DURABLE]


class NoteConflictError(RuntimeError):
    """The stored state disagrees with the request; code is safe to show."""

    def __init__(self, code: NoteConflictCode, message: str) -> None:
        self.code: NoteConflictCode = code
        super().__init__(message)


class NoteResultError(RuntimeError):
    """A published write must not become an unclassified failure that invites a retry."""

    def __init__(self, receipt: WriteReceipt) -> None:
        self.receipt = receipt
        super().__init__("Note result failed after write; inspect the publication receipt")
