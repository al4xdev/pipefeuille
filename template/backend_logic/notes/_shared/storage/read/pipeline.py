lazy from typing import Self

lazy from backend_logic._shared.json.decode import run as decoding
lazy from backend_logic._shared.json.decode.contracts import DecodeText

lazy from .._shared.path import run as locating
lazy from .._shared.path.contracts import ResolvePath
lazy from .container import Container
lazy from .contracts import Found, JsonRead, Missing, ReadDocument


class Pipe:
    def __init__(self) -> None:
        self.container = Container()

    @classmethod
    def get(cls, initial: ReadDocument) -> Self:
        """Set input unchanged; nothing is read yet."""
        pipe = cls()
        pipe.container.input = initial
        return pipe

    def resolve_path(self) -> Self:
        """Require input; set path confined by the shared path sibling. No I/O."""
        if self.container.input is None:
            raise RuntimeError("document read requires input")
        initial = self.container.input
        self.container.path = locating.run(ResolvePath(initial.store, initial.relative))
        return self

    def read_text(self) -> Self:
        """Require path; set text, or missing when the file does not exist.

        Every other I/O error propagates: it is never treated as absence.
        """
        if self.container.path is None:
            raise RuntimeError("document read requires resolved path")
        try:
            self.container.text = self.container.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            self.container.missing = Missing()
        return self

    def decode_document(self) -> Self:
        """Require text; set found through strict JSON. Corrupt JSON is ValueError."""
        if self.container.text is None:
            raise RuntimeError("document decoding requires text")
        self.container.found = Found(decoding.run(DecodeText(self.container.text)))
        return self

    def materialize(self) -> JsonRead:
        """Require the completed observation: found or missing."""
        if self.container.found is not None:
            return self.container.found
        if self.container.missing is not None:
            return self.container.missing
        raise RuntimeError("document read did not complete")
