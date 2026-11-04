lazy from .contracts import JsonRead, ReadDocument
lazy from .pipeline import Pipe


def run(initial: ReadDocument) -> JsonRead:
    pipe = (
        Pipe
            .get(initial)
                .resolve_path()
                    .read_text()
    )
    if pipe.container.missing is None:
        pipe.decode_document()
    return pipe.materialize()
