lazy from dataclasses import dataclass

lazy from .contracts import NotesRequest
lazy from .list.contracts import NoteNames
lazy from .prepare.contracts import Resources
lazy from .save.contracts import SavedNote


@dataclass
class Container:
    input: NotesRequest | None = None
    prepared: Resources | None = None
    listed: NoteNames | None = None
    saved: SavedNote | None = None
