"""The validated JSON value: what every ingestion boundary hands to its consumer."""

lazy from dataclasses import dataclass

type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]


@dataclass(frozen=True)
class Validated:
    """Validation completed; value may legitimately be JSON null."""

    value: JsonValue
