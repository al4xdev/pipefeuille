lazy from dataclasses import dataclass

lazy from .contracts import Validated


@dataclass
class Container:
    candidate: object = None
    validated: Validated | None = None
