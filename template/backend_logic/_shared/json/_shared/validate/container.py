lazy from dataclasses import dataclass

lazy from backend_logic._shared.json.contracts import Validated


@dataclass
class Container:
    candidate: object = None
    validated: Validated | None = None
