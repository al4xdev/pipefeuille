lazy from dataclasses import dataclass

lazy from backend_logic._shared.json.contracts import JsonValue
lazy from backend_logic.notes._shared.storage.contracts import FileStore


@dataclass(frozen=True)
class ReadDocument:
    """Read-only lookup. The caller holds the named lock if it will write afterwards."""

    store: FileStore
    relative: str


@dataclass(frozen=True)
class Found:
    """Read completed; value may legitimately be JSON null."""

    value: JsonValue


@dataclass(frozen=True)
class Missing:
    """Absence observed by a completed read, distinct from a read not executed."""


type JsonRead = Found | Missing
