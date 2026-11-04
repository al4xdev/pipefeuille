lazy from .contracts import ScanDirectory
lazy from .pipeline import Pipe


def run(initial: ScanDirectory) -> tuple[str, ...]:
    """List the regular files directly beneath one store directory, without opening them.

    Effects:
        reads: the directory entries; a missing directory lists nothing and is not created.
    Repeat:
        safe
    Loops:
        none
    Concurrency:
        free
    Raises:
        ValueError: the directory is not strictly beneath the store root.
    """
    return (
        Pipe
            .get(initial)
                .resolve_directory()
                    .read_entries()
                        .select_files()
                            .materialize()
    )
