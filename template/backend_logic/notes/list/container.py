"""Fixed local intermediate state, also the boundary for segment fixtures."""

lazy from dataclasses import dataclass

lazy from backend_logic._shared.note_name.contracts import NoteName

lazy from .contracts import ListNotes


@dataclass
class Container:
    input: ListNotes | None = None
    files: tuple[str, ...] | None = None
    stems: tuple[str, ...] | None = None  # candidates, not yet admitted
    names: tuple[NoteName, ...] | None = None  # admitted by _shared/note_name
