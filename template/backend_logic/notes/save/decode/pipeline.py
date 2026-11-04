lazy from datetime import datetime, timedelta
lazy from typing import Self

lazy from backend_logic._shared.json.contracts import JsonValue
lazy from backend_logic._shared.note_name import run as naming
lazy from backend_logic._shared.note_name.contracts import NoteValidationError

lazy from ..contracts import AuthorId, NoteRecord, Revision
lazy from .container import Container


class Pipe:
    def __init__(self) -> None:
        self.container = Container()

    @classmethod
    def get(cls, initial: JsonValue) -> Self:
        """Set document unchanged; it is untrusted stored JSON until admitted."""
        pipe = cls()
        pipe.container.document = initial
        return pipe

    def require_object(self, *, keys: frozenset[str]) -> Self:
        """Require document; set fields only for an object with exactly the declared keys."""
        document = self.container.document
        if not isinstance(document, dict):
            raise ValueError("stored note must be a JSON object")
        if frozenset(document) != keys:
            # Unknown keys fail instead of silently disappearing on the next write.
            raise ValueError("stored note has unexpected or missing fields")
        self.container.fields = document
        return self

    def admit_record(self) -> Self:
        """Require fields; set record after checking every declared type. No defaults.

        The name passes the same note_name authority as save input; a stored name it
        rejects is a corrupt document (ValueError), not the client's invalid_name.
        """
        fields = self.container.fields
        if fields is None:
            raise RuntimeError("note admission requires object fields")
        schema_version = fields["schema_version"]
        name = fields["name"]
        body = fields["body"]
        author_id = fields["author_id"]
        revision = fields["revision"]
        updated_at = fields["updated_at"]
        if schema_version != 1 or type(schema_version) is not int:
            raise ValueError("unsupported note schema version")
        if not isinstance(name, str) or not isinstance(body, str):
            raise ValueError("note name and body must be text")
        if not isinstance(author_id, str) or not isinstance(updated_at, str):
            raise ValueError("note author and timestamp must be text")
        if type(revision) is not int or revision <= 0:
            raise ValueError("note revision must be a positive integer")
        timestamp = datetime.fromisoformat(updated_at)
        if timestamp.utcoffset() != timedelta(0):
            raise ValueError("note timestamp must be aware UTC")
        try:
            admitted_name = naming.run(name)
        except NoteValidationError as error:
            raise ValueError("stored note name is invalid") from error
        self.container.record = NoteRecord(
            schema_version=1,
            name=admitted_name,
            body=body,
            author_id=AuthorId(author_id),
            revision=Revision(revision),
            updated_at=timestamp,
        )
        return self

    def materialize(self) -> NoteRecord:
        """Require admitted record; return it."""
        if self.container.record is None:
            raise RuntimeError("note decode requires admitted record")
        return self.container.record
