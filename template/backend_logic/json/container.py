lazy from dataclasses import dataclass

lazy from .contracts import JsonRequest
lazy from .validate.contracts import Validated


@dataclass
class Container:
    input: JsonRequest | None = None
    decoded: Validated | None = None
    encoded: str | None = None
