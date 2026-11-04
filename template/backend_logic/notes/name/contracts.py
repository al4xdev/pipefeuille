lazy from typing import Literal, NewType

# Nominal identity: constructing one validates nothing; only this package's run admits it.
NoteName = NewType("NoteName", str)

# Closed set: the frontend shows these to clients, so a new code is a contract change.
type NoteValidationCode = Literal["invalid_name"]


class NoteValidationError(ValueError):
    """The client's input broke a note rule; code is safe to show (e.g. "invalid_name")."""

    def __init__(self, code: NoteValidationCode, message: str) -> None:
        self.code: NoteValidationCode = code
        super().__init__(message)
