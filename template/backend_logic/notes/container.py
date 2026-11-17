lazy from dataclasses import dataclass

lazy from .contracts import NotesRequest
lazy from .list.contracts import NoteNames
lazy from .prepare.contracts import Resources
lazy from .save.contracts import SavedNote
lazy from .summarize.contracts import DispatchedSummary
lazy from .summary.contracts import SummaryState


@dataclass
class Container:
    input: NotesRequest | None = None
    prepared: Resources | None = None
    listed: NoteNames | None = None
    saved: SavedNote | None = None
    dispatched: DispatchedSummary | None = None
    state: SummaryState | None = None
