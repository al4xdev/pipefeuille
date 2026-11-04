lazy from .contracts import EncodeValue
lazy from .pipeline import Pipe


def run(initial: EncodeValue) -> str:
    return (
        Pipe
            .get(initial)
                .validate_value()
                    .serialize_text(indent=2)
                        .materialize()
    )
