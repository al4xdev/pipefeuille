lazy from dataclasses import dataclass


@dataclass(frozen=True)
class ValidateValue:
    """Any Python value whose JSON-ness is not yet known; nothing about it is trusted."""

    candidate: object
