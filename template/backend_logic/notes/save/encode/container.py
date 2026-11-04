lazy from dataclasses import dataclass

lazy from ..contracts import NoteRecord
lazy from .contracts import NoteDocument


@dataclass
class Container:
    record: NoteRecord | None = None
    document: NoteDocument | None = None
