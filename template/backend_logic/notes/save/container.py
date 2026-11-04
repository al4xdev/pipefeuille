lazy from dataclasses import dataclass
lazy from datetime import datetime

lazy from backend_logic.storage.write.contracts import WriteReceipt

lazy from ..name.contracts import NoteName
lazy from .contracts import CurrentRead, NoteRecord, Revision, SaveNote
lazy from .encode.contracts import NoteDocument


@dataclass
class Container:
    input: SaveNote | None = None
    name: NoteName | None = None
    relative_path: str | None = None
    current: CurrentRead | None = None
    revision: Revision | None = None
    timestamp: datetime | None = None
    record: NoteRecord | None = None
    document: NoteDocument | None = None
    receipt: WriteReceipt | None = None
