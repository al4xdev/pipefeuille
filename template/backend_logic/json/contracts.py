"""The use cases this family answers. Each type lives in the package that owns it."""

lazy from .decode.contracts import DecodeText
lazy from .encode.contracts import EncodeValue

type JsonRequest = DecodeText | EncodeValue
