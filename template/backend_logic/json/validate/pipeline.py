lazy import math
lazy from typing import Self, cast

lazy from .container import Container
lazy from .contracts import JsonValue, Validated


def _require_scalar_text(text: str) -> None:
    # json.loads accepts escaped lone surrogates ("\ud800"); they cannot be stored as UTF-8.
    try:
        text.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError("JSON text must be valid Unicode scalar values") from error


def _require_json(value: object) -> None:
    if value is None or type(value) in (bool, int):
        return
    if type(value) is str:
        _require_scalar_text(value)
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("JSON numbers must be finite")
        return
    if type(value) is list:
        for item in value:
            _require_json(item)
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise TypeError("JSON object keys must be strings")
            _require_scalar_text(key)
            _require_json(item)
        return
    raise TypeError("Value is not a JSON value")


class Pipe:
    def __init__(self) -> None:
        self.container = Container()

    @classmethod
    def get(cls, initial: object) -> Self:
        """Set the candidate unchanged; nothing is trusted yet."""
        pipe = cls()
        pipe.container.candidate = initial
        return pipe

    def validate_value(self) -> Self:
        """Read candidate; verify it, never repair it. Set validated, narrowed to JsonValue.

        No implicit tuple encoding, non-string keys, lone surrogates or nonfinite numbers.
        Nonfinite numbers and surrogates are ValueError; non-JSON types are TypeError.
        """
        candidate = self.container.candidate
        _require_json(candidate)
        # The only narrowing from object: everything above has just been verified.
        self.container.validated = Validated(cast(JsonValue, candidate))
        return self

    def materialize(self) -> JsonValue:
        """Require validated; return its value, which may legitimately be None."""
        if self.container.validated is None:
            raise RuntimeError("JSON value must be validated first")
        return self.container.validated.value
