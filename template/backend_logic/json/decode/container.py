lazy from dataclasses import dataclass

lazy from ..validate.contracts import Validated
lazy from .contracts import DecodeText, Parsed


@dataclass
class Container:
    input: DecodeText | None = None
    parsed: Parsed | None = None
    validated: Validated | None = None
