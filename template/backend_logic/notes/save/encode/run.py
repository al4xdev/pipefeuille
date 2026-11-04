lazy from ..contracts import NoteRecord
lazy from .contracts import NoteDocument
lazy from .pipeline import Pipe


def run(initial: NoteRecord) -> NoteDocument:
    return (
        Pipe
            .get(initial)
                .encode_fields()
                    .materialize()
    )
