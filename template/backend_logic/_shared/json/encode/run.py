lazy from .contracts import EncodeValue
lazy from .pipeline import Pipe


def run(initial: EncodeValue) -> str:
    """Serialize a JSON value; the text never contains what decode would reject.

    Effects:
        pure
    Repeat:
        safe
    Loops:
        none
    Concurrency:
        free
    Raises:
        ValueError: a non-finite number or a lone surrogate.
        TypeError: a value or key that is not JSON.
    """
    return (
        Pipe
            .get(initial)
                .validate_value()
                    .serialize_text(indent=2)
                        .materialize()
    )
