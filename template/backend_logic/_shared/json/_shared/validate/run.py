lazy from backend_logic._shared.json.contracts import JsonValue

lazy from .contracts import ValidateValue
lazy from .pipeline import Pipe


def run(initial: ValidateValue) -> JsonValue:
    """Verify that a Python value is JSON and narrow it; shared by decode and encode.

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
                    .materialize()
    )
