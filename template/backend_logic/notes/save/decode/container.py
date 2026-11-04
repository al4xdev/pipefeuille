lazy from dataclasses import dataclass

lazy from backend_logic._shared.json.contracts import JsonValue

lazy from ..contracts import NoteRecord
lazy from .contracts import NoteFields


@dataclass
class Container:
    document: JsonValue | None = None
    fields: NoteFields | None = None
    record: NoteRecord | None = None
