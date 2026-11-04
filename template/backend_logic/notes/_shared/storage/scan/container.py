lazy from dataclasses import dataclass
lazy from pathlib import Path

lazy from .contracts import ScanDirectory


@dataclass
class Container:
    input: ScanDirectory | None = None
    directory: Path | None = None
    entries: tuple[Path, ...] | None = None
    files: tuple[str, ...] | None = None
