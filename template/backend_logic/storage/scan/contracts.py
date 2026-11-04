lazy from dataclasses import dataclass

lazy from ..path.contracts import FileStore


@dataclass(frozen=True)
class ScanDirectory:
    """Immediate entries only. A directory never written yet is observed as empty."""

    store: FileStore
    relative: str
