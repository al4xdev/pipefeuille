lazy from dataclasses import dataclass
lazy from pathlib import Path


@dataclass(frozen=True)
class FileStore:
    """An existing absolute root; every operation is relative to it. One per application."""

    root: Path

    def __post_init__(self) -> None:
        if not self.root.is_absolute() or not self.root.is_dir():
            raise NotADirectoryError("FileStore requires an existing absolute directory root")


@dataclass(frozen=True)
class ResolvePath:
    """A plain "a/b.json" form; anything else is rejected, never normalized."""

    store: FileStore
    relative: str
