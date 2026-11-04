lazy from typing import Self

lazy from .container import Container
lazy from .contracts import JsonRequest
lazy from .decode import run as decoding
lazy from .decode.contracts import DecodeText
lazy from .encode import run as encoding
lazy from .encode.contracts import EncodeValue
lazy from .validate.contracts import JsonValue, Validated


class Pipe:
    def __init__(self) -> None:
        self.container = Container()

    @classmethod
    def get(cls, initial: JsonRequest) -> Self:
        """Set input unchanged; run chooses the branch."""
        pipe = cls()
        pipe.container.input = initial
        return pipe

    def decode_text(self, request: DecodeText) -> Self:
        """Set decoded through the decode child. Rejection is ValueError."""
        self.container.decoded = Validated(decoding.run(request))
        return self

    def encode_value(self, request: EncodeValue) -> Self:
        """Set encoded through the encode child. Rejection is ValueError or TypeError."""
        self.container.encoded = encoding.run(request)
        return self

    def materialize(self) -> JsonValue:
        """Require exactly the branch that ran; return its product."""
        if self.container.decoded is not None:
            return self.container.decoded.value
        if self.container.encoded is not None:
            return self.container.encoded
        raise RuntimeError("a JSON branch must run before materialize")
