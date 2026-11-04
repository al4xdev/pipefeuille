lazy from ..contracts import NoteRecord
lazy from .contracts import NoteDocument
lazy from .pipeline import Pipe


def run(initial: NoteRecord) -> NoteDocument:
    """Encode a NoteRecord as its persisted JSON document.

    Effects:
        pure
    Repeat:
        safe
    Loops:
        none
    Concurrency:
        free
    """
    return (
        Pipe
            .get(initial)
                .encode_fields()
                    .materialize()
    )
