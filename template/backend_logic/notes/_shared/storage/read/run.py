lazy from .contracts import JsonRead, ReadDocument
lazy from .pipeline import Pipe


def run(initial: ReadDocument) -> JsonRead:
    """Read one JSON document; absence is observed, corruption propagates.

    Effects:
        reads: one file beneath the store root.
    Repeat:
        safe
    Loops:
        none
    Concurrency:
        caller-locks: a consistent read-modify-write needs the caller's named lock.
    Raises:
        ValueError: the path leaves the store root, or the file is not strict JSON.
        OSError: any read failure other than absence.
    """
    pipe = (
        Pipe
            .get(initial)
                .resolve_path()
                    .read_text()
    )
    if pipe.container.missing is None:
        pipe.decode_document()
    return pipe.materialize()
