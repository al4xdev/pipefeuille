lazy from dataclasses import dataclass
lazy from pathlib import Path

lazy from backend_logic.storage.lock.contracts import LockRegistry
lazy from backend_logic.storage.path.contracts import FileStore

lazy from .contracts import PrepareResources, UtcClock


@dataclass
class Container:
    input: PrepareResources | None = None
    root: Path | None = None
    store: FileStore | None = None
    locks: LockRegistry | None = None
    clock: UtcClock | None = None
