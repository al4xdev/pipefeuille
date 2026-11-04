lazy from dataclasses import dataclass

lazy from backend_logic._shared.json.contracts import Validated

lazy from .contracts import EncodeValue


@dataclass
class Container:
    input: EncodeValue | None = None
    validated: Validated | None = None
    text: str | None = None
