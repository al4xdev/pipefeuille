lazy from dataclasses import dataclass
lazy from datetime import UTC, datetime
lazy from pathlib import Path

lazy from backend_logic.notes.save.contracts import AuthorId
lazy from backend_logic.storage.lock.contracts import LockRegistry
lazy from backend_logic.storage.path.contracts import FileStore


@dataclass(frozen=True)
class PrepareResources:
    """Process-level configuration loaded by the entrypoint, not by any child."""

    data_root: Path
    author_id: AuthorId


class UtcClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


@dataclass(frozen=True)
class Resources:
    """Application-lifetime resources with one owner. Not a session or request container."""

    data_root: Path
    store: FileStore
    locks: LockRegistry
    clock: UtcClock
    author_id: AuthorId
