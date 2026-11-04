lazy from .contracts import ScanDirectory
lazy from .pipeline import Pipe


def run(initial: ScanDirectory) -> tuple[str, ...]:
    return (
        Pipe
            .get(initial)
                .resolve_directory()
                    .read_entries()
                        .select_files()
                            .materialize()
    )
