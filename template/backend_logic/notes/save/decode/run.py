lazy from backend_logic.json.validate.contracts import JsonValue

lazy from ..contracts import NoteRecord
lazy from .pipeline import Pipe


def run(initial: JsonValue) -> NoteRecord:
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
