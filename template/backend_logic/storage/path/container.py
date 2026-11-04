lazy from dataclasses import dataclass
lazy from pathlib import Path

lazy from .contracts import ResolvePath


@dataclass
class Container:
    input: ResolvePath | None = None
    segments: tuple[str, ...] | None = None
    path: Path | None = None
