lazy from typing import Self

lazy from .container import Container
lazy from .contracts import NoteName, NoteValidationError


class Pipe:
    def __init__(self) -> None:
        self.container = Container()

    @classmethod
    def get(cls, initial: str) -> Self:
        """Set input unchanged; no normalization happens here or later."""
        pipe = cls()
        pipe.container.input = initial
        return pipe

    def validate_grammar(self, *, allowed: str, max_length: int) -> Self:
        """Require input; set name only if nonempty, within max_length and made of allowed.

        validate_* never corrects: padded names are rejected, not trimmed. Raise
        NoteValidationError("invalid_name"); no I/O.
        """
        name = self.container.input
        if name is None:
            raise RuntimeError("note name admission requires input")
        if not name or len(name) > max_length:
            raise NoteValidationError("invalid_name", "Note name is empty or too long.")
        if not all(character in allowed for character in name):
            raise NoteValidationError("invalid_name", "Note name may use letters, digits, - and _.")
        self.container.name = NoteName(name)
        return self

    def materialize(self) -> NoteName:
        """Require admitted name; constructing the NewType alone is not validation."""
        if self.container.name is None:
            raise RuntimeError("note name output requires an admitted name")
        return self.container.name
