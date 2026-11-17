lazy from dataclasses import dataclass

lazy from backend_logic._shared.agents.contracts import RunId
lazy from backend_logic._shared.note_name.contracts import NoteName


@dataclass(frozen=True)
class DispatchSummary:
    """Summarize one stored note with an agent; the answer is read later (ReadSummary)."""

    name: str


@dataclass(frozen=True)
class DispatchedSummary:
    """The agent run was handed over; run_id is how ReadSummary finds its answer."""

    name: NoteName
    run_id: RunId


class NoteMissingError(LookupError):
    """No stored note has this name; nothing was handed over."""
