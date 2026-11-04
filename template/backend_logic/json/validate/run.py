lazy from .contracts import JsonValue
lazy from .pipeline import Pipe


def run(initial: object) -> JsonValue:
    return (
        Pipe
            .get(initial)
                .validate_value()
                    .materialize()
    )
