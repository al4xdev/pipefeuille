lazy from backend_logic.notes._shared.storage.contracts import FileStore

lazy from .contracts import ListNotes, NoteNames
lazy from .pipeline import Pipe


def run(initial: ListNotes, *, store: FileStore) -> NoteNames:
    """List the names of the stored notes, sorted.

    Effects:
        reads: the entries of the notes directory, without opening any file.
    Repeat:
        safe
    Loops:
        none
    Concurrency:
        free: a note saved meanwhile may or may not appear.
    Raises:
        ValueError: a file in the notes directory has an invalid name; listing fails loudly.
    """
    return (
        Pipe
            .get(initial)
                .scan_directory(store=store, relative="notes")
                    .select_stems(suffix=".json")
                        .admit_names()
                            .sort_names()
                                .materialize()
    )
