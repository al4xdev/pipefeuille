lazy from dataclasses import dataclass
lazy from pathlib import Path

lazy from .contracts import Found, Missing, ReadDocument


@dataclass
class Container:
    input: ReadDocument | None = None
    path: Path | None = None
    text: str | None = None
    missing: Missing | None = None
    found: Found | None = None
