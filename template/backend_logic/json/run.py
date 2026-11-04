lazy from typing import assert_never, overload

lazy from .contracts import JsonRequest
lazy from .decode.contracts import DecodeText
lazy from .encode.contracts import EncodeValue
lazy from .pipeline import Pipe
lazy from .validate.contracts import JsonValue


@overload
def run(initial: DecodeText) -> JsonValue: ...
@overload
def run(initial: EncodeValue) -> str: ...
def run(initial: JsonRequest) -> JsonValue:
    pipe = Pipe.get(initial)
    match initial:
        case DecodeText():
            pipe.decode_text(initial)
        case EncodeValue():
            pipe.encode_value(initial)
        case _:
            assert_never(initial)
    return pipe.materialize()
