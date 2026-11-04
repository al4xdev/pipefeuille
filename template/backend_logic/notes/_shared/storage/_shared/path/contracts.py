lazy from dataclasses import dataclass

lazy from backend_logic.notes._shared.storage.contracts import FileStore


@dataclass(frozen=True)
class ResolvePath:
    """A plain "a/b.json" form; anything else is rejected, never normalized."""

    store: FileStore
    relative: str
