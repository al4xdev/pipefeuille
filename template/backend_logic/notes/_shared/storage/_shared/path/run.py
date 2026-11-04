lazy from pathlib import Path

lazy from .contracts import ResolvePath
lazy from .pipeline import Pipe


def run(initial: ResolvePath) -> Path:
    return (
        Pipe
            .get(initial)
                .validate_segments()
                    .join_root()
                        .materialize()
    )
