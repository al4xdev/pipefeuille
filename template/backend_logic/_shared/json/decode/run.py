lazy from backend_logic._shared.json.contracts import JsonValue

lazy from .contracts import DecodeText
lazy from .pipeline import Pipe


def run(initial: DecodeText) -> JsonValue:
    """Parse untrusted text as strict JSON: the only place the library's Any is contained.

    Effects:
        pure
    Repeat:
        safe
    Loops:
        none
    Concurrency:
        free
    Raises:
        ValueError: not JSON, duplicate keys, NaN or Infinity, or nesting too deep.
    """
    return (
        Pipe
            .get(initial)
                .parse_text()
                    .validate_value()
                        .materialize()
    )
