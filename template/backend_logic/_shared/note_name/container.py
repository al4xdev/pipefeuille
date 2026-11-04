lazy from dataclasses import dataclass

lazy from .contracts import NoteName


@dataclass
class Container:
    input: str | None = None
    name: NoteName | None = None
