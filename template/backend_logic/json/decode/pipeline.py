lazy import json
lazy from typing import Self

lazy from ..validate import run as validating
lazy from ..validate.contracts import JsonValue, Validated
lazy from .container import Container
lazy from .contracts import DecodeText, Parsed


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("JSON object contains duplicate keys")
        result[key] = value
    return result


def _reject_constant(name: str) -> None:
    raise ValueError(f"JSON constant {name} is not allowed")


class Pipe:
    def __init__(self) -> None:
        self.container = Container()

    @classmethod
    def get(cls, initial: DecodeText) -> Self:
        """Set input unchanged; nothing is parsed yet."""
        pipe = cls()
        pipe.container.input = initial
        return pipe

    def parse_text(self) -> Self:
        """Require input; set parsed, widened to object. Duplicate keys, NaN/Infinity and
        nesting deeper than the interpreter allows are rejected as ValueError."""
        if self.container.input is None:
            raise RuntimeError("JSON decoding requires input")
        try:
            value: object = json.loads(
                self.container.input.text,
                object_pairs_hook=_unique_object,
                parse_constant=_reject_constant,
            )
        except RecursionError as error:
            raise ValueError("JSON nesting is too deep") from error
        self.container.parsed = Parsed(value)
        return self

    def validate_value(self) -> Self:
        """Require parsed; set validated through the shared validate sibling.

        Parsed text can only fail with ValueError here (lone surrogates).
        """
        if self.container.parsed is None:
            raise RuntimeError("JSON validation requires parsed text")
        try:
            self.container.validated = Validated(validating.run(self.container.parsed.value))
        except RecursionError as error:
            raise ValueError("JSON nesting is too deep") from error
        return self

    def materialize(self) -> JsonValue:
        """Require validated; return its value, which may legitimately be None."""
        if self.container.validated is None:
            raise RuntimeError("decoded JSON must be validated first")
        return self.container.validated.value
