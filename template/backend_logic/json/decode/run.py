lazy from ..validate.contracts import JsonValue
lazy from .contracts import DecodeText
lazy from .pipeline import Pipe


def run(initial: DecodeText) -> JsonValue:
    return (
        Pipe
            .get(initial)
                .parse_text()
                    .validate_value()
                        .materialize()
    )
