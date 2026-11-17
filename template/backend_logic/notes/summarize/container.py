lazy from dataclasses import dataclass

lazy from backend_logic._shared.agents.contracts import RunId, Submission
lazy from backend_logic._shared.json.contracts import JsonValue
lazy from backend_logic._shared.note_name.contracts import NoteName
lazy from backend_logic.notes.save.contracts import NoteRecord

lazy from .contracts import DispatchSummary


@dataclass
class Container:
    input: DispatchSummary | None = None
    name: NoteName | None = None
    relative_path: str | None = None
    record: NoteRecord | None = None
    view: dict[str, JsonValue] | None = None  # what the agent gets: no internal ids
    submission: Submission | None = None
    run_id: RunId | None = None
