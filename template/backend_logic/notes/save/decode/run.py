lazy from backend_logic._shared.json.contracts import JsonValue

lazy from ..contracts import NoteRecord
lazy from .pipeline import Pipe


def run(initial: JsonValue) -> NoteRecord:
    """Admit a stored JSON document as a NoteRecord.

    Effects:
        pure
    Repeat:
        safe
    Loops:
        none
    Concurrency:
        free
    Raises:
        ValueError: the document is not a version-1 note record.
    """
    return (
        Pipe
            .get(initial)
                .require_object(
                    keys=frozenset(
                        {"schema_version", "name", "body", "author_id", "revision", "updated_at"}
                    )
                )
                    .admit_record()
                        .materialize()
    )
