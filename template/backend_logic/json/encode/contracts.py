lazy from dataclasses import dataclass

lazy from ..validate.contracts import JsonValue


@dataclass(frozen=True)
class EncodeValue:
    """A value to store; validated again because the static type does not prove finiteness."""

    value: JsonValue
