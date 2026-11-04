lazy from pathlib import Path

lazy from .contracts import ResolvePath
lazy from .pipeline import Pipe


def run(initial: ResolvePath) -> Path:
    """Confine a store-relative path beneath the store root; shared by read, write and scan.

    Effects:
        pure: string checks and a join; the file system is not touched.
    Repeat:
        safe
    Loops:
        none
    Concurrency:
        free
    Raises:
        ValueError: the path is absolute, empty or climbs out of the root; never normalized.
    """
    return (
        Pipe
            .get(initial)
                .validate_segments()
                    .join_root()
                        .materialize()
    )
