lazy from datetime import timedelta
lazy from typing import Literal, Self

lazy from backend_logic._shared.note_name import run as naming
lazy from backend_logic.notes._shared.storage.contracts import FileStore
lazy from backend_logic.notes._shared.storage.read import run as reading
lazy from backend_logic.notes._shared.storage.read.contracts import Found, ReadDocument
lazy from backend_logic.notes._shared.storage.write import run as writing
lazy from backend_logic.notes._shared.storage.write.contracts import (
    AtomicWriteError,
    PublicationStatus,
    WriteDocument,
)

lazy from .container import Container
lazy from .contracts import (
    Clock,
    CurrentRead,
    NoteConflictError,
    NoteRecord,
    Revision,
    SavedNote,
    SaveNote,
)
lazy from .decode import run as decoding
lazy from .encode import run as encoding


class Pipe:
    def __init__(self) -> None:
        self.container = Container()

    @classmethod
    def get(cls, initial: SaveNote) -> Self:
        """Set input unchanged; nothing is admitted yet."""
        pipe = cls()
        pipe.container.input = initial
        return pipe

    def validate_name(self) -> Self:
        """Require input; set name admitted by the shared note_name authority.

        Propagate NoteValidationError("invalid_name"); no I/O, no correction.
        """
        if self.container.input is None:
            raise RuntimeError("note save requires input")
        self.container.name = naming.run(self.container.input.name)
        return self

    def resolve_path(self, *, directory: str, suffix: str) -> Self:
        """Require name; set confined store-relative path. No I/O."""
        if self.container.name is None:
            raise RuntimeError("note path requires validated name")
        self.container.relative_path = f"{directory}/{self.container.name}{suffix}"
        return self

    def read_current(self, *, store: FileStore) -> Self:
        """Require name/path and the named lock; set current. Read-only I/O.

        Corrupt or misfiled documents fail; they are never treated as absence.
        """
        if self.container.name is None or self.container.relative_path is None:
            raise RuntimeError("current note lookup requires name and path")
        read = reading.run(ReadDocument(store, self.container.relative_path))
        record = decoding.run(read.value) if isinstance(read, Found) else None
        if record is not None and record.name != self.container.name:
            raise ValueError("stored note name does not match its path")
        self.container.current = CurrentRead(record)
        return self

    def admit_creation(self, *, initial_revision: Literal[1]) -> Self:
        """Require current; absent note and no expected_revision. Set revision. No write."""
        if self.container.input is None or self.container.current is None:
            raise RuntimeError("creation admission requires input and completed lookup")
        if self.container.current.record is not None:
            raise NoteConflictError("note_exists", "Note already exists. Confirm replacement.")
        if self.container.input.expected_revision is not None:
            raise NoteConflictError("note_missing", "The note no longer exists.")
        self.container.revision = Revision(initial_revision)
        return self

    def admit_replacement(self) -> Self:
        """Require current; existing note with matching expected_revision. Increment once."""
        if self.container.input is None or self.container.current is None:
            raise RuntimeError("replacement admission requires input and completed lookup")
        current = self.container.current.record
        if current is None:
            raise NoteConflictError("note_missing", "The note no longer exists.")
        if self.container.input.expected_revision != current.revision:
            raise NoteConflictError("revision_conflict", "The note changed; reload it first.")
        self.container.revision = Revision(current.revision + 1)
        return self

    def read_time(self, *, clock: Clock) -> Self:
        """Require admitted revision; sample and validate an aware UTC timestamp."""
        if self.container.revision is None:
            raise RuntimeError("time sampling requires admitted revision")
        timestamp = clock.now()
        if timestamp.utcoffset() != timedelta(0):
            raise ValueError("note clock must return an aware UTC timestamp")
        self.container.timestamp = timestamp
        return self

    def prepare_record(self, *, schema_version: Literal[1]) -> Self:
        """Require admitted name/revision/timestamp; set record. A candidate, not a write."""
        if (
            self.container.input is None
            or self.container.name is None
            or self.container.revision is None
            or self.container.timestamp is None
        ):
            raise RuntimeError("record preparation requires admitted name, revision and time")
        self.container.record = NoteRecord(
            schema_version=schema_version,
            name=self.container.name,
            body=self.container.input.body,
            author_id=self.container.input.author_id,
            revision=self.container.revision,
            updated_at=self.container.timestamp,
        )
        return self

    def encode_record(self) -> Self:
        """Require record; set document through the encode child. No I/O."""
        if self.container.record is None:
            raise RuntimeError("note encoding requires prepared record")
        self.container.document = encoding.run(self.container.record)
        return self

    def commit(self, *, store: FileStore) -> Self:
        """Require path/document and named lock; publish once and retain WriteReceipt.

        Propagate AtomicWriteError unchanged, keeping its receipt. No retry.
        """
        if self.container.relative_path is None or self.container.document is None:
            raise RuntimeError("note publication requires path and document")
        if self.container.receipt is not None:
            raise RuntimeError("note publication was already attempted")
        try:
            self.container.receipt = writing.run(
                WriteDocument(store, self.container.relative_path, self.container.document)
            )
        except AtomicWriteError as error:
            self.container.receipt = error.receipt
            raise
        return self

    def materialize(self) -> SavedNote:
        """Require record and DURABLE receipt; partial publication cannot materialize success."""
        if self.container.record is None or self.container.receipt is None:
            raise RuntimeError("note save result requires record and publication receipt")
        if self.container.receipt.status is not PublicationStatus.DURABLE:
            raise RuntimeError("note save result requires durable publication")
        return SavedNote(self.container.record, PublicationStatus.DURABLE)
