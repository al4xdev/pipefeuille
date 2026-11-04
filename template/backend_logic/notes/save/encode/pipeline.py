lazy from typing import Self

lazy from ..contracts import NoteRecord
lazy from .container import Container
lazy from .contracts import NoteDocument


class Pipe:
    def __init__(self) -> None:
        self.container = Container()

    @classmethod
    def get(cls, initial: NoteRecord) -> Self:
        """Set record; it is already admitted by the parent."""
        pipe = cls()
        pipe.container.record = initial
        return pipe

    def encode_fields(self) -> Self:
        """Require record; set document with every schema1 field. Inverse of save/decode."""
        record = self.container.record
        if record is None:
            raise RuntimeError("note encoding requires record")
        self.container.document = {
            "schema_version": record.schema_version,
            "name": record.name,
            "body": record.body,
            "author_id": record.author_id,
            "revision": record.revision,
            "updated_at": record.updated_at.isoformat(),
        }
        return self

    def materialize(self) -> NoteDocument:
        """Require document; return it for publication."""
        if self.container.document is None:
            raise RuntimeError("note encoding requires document")
        return self.container.document
