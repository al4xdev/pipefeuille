"""The values this grouping hands to every consumer; each operation is its own package.

A grouping has no run: callers call the operation they need (decode, encode) directly.
"""

lazy from dataclasses import dataclass

type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]


@dataclass(frozen=True)
class Validated:
    """Validation completed; value may legitimately be JSON null."""

    value: JsonValue
