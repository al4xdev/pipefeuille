"""The handle this grouping hands to every consumer; each operation is its own package.

A grouping has no run: callers call the operation they need (read, write, scan, lock)
directly.
"""

lazy from dataclasses import dataclass
lazy from pathlib import Path


@dataclass(frozen=True)
class FileStore:
    """An existing absolute root; every operation is relative to it. One per application."""

    root: Path

    def __post_init__(self) -> None:
        if not self.root.is_absolute() or not self.root.is_dir():
            raise NotADirectoryError("FileStore requires an existing absolute directory root")
