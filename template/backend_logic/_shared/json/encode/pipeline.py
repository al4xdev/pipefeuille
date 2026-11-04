lazy import json
lazy from typing import Self

lazy from backend_logic._shared.json.contracts import Validated

lazy from .._shared.validate import run as validating
lazy from .._shared.validate.contracts import ValidateValue
lazy from .container import Container
lazy from .contracts import EncodeValue


class Pipe:
    def __init__(self) -> None:
        self.container = Container()

    @classmethod
    def get(cls, initial: EncodeValue) -> Self:
        """Set input unchanged; nothing is validated yet."""
        pipe = cls()
        pipe.container.input = initial
        return pipe

    def validate_value(self) -> Self:
        """Require input; set validated through the shared validate sibling."""
        if self.container.input is None:
            raise RuntimeError("JSON encoding requires input")
        candidate = ValidateValue(self.container.input.value)
        self.container.validated = Validated(validating.run(candidate))
        return self

    def serialize_text(self, *, indent: int) -> Self:
        """Require validated; set UTF-8-safe text with a final newline. No I/O."""
        if self.container.validated is None:
            raise RuntimeError("JSON serialization requires a validated value")
        text = json.dumps(
            self.container.validated.value, ensure_ascii=False, allow_nan=False, indent=indent
        )
        self.container.text = text + "\n"
        return self

    def materialize(self) -> str:
        """Require text; return it."""
        if self.container.text is None:
            raise RuntimeError("encoded JSON text is required")
        return self.container.text
