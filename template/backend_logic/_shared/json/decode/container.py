lazy from dataclasses import dataclass

lazy from backend_logic._shared.json.contracts import Validated

lazy from .contracts import DecodeText, Parsed


@dataclass
class Container:
    input: DecodeText | None = None
    parsed: Parsed | None = None
    validated: Validated | None = None
