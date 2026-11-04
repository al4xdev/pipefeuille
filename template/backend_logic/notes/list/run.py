lazy from backend_logic.storage.path.contracts import FileStore

lazy from .contracts import ListNotes, NoteNames
lazy from .pipeline import Pipe


def run(initial: ListNotes, *, store: FileStore) -> NoteNames:
    return (
        Pipe
            .get(initial)
                .scan_directory(store=store, relative="notes")
                    .select_stems(suffix=".json")
                        .admit_names()
                            .sort_names()
                                .materialize()
    )
