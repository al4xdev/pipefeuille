lazy from backend_logic._shared.json.contracts import JsonValue

lazy from .contracts import ValidateValue
lazy from .pipeline import Pipe


def run(initial: ValidateValue) -> JsonValue:
    return (
        Pipe
            .get(initial)
                .validate_value()
                    .materialize()
    )
