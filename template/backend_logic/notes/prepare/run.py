lazy from .contracts import PrepareResources, Resources
lazy from .pipeline import Pipe


def run(initial: PrepareResources) -> Resources:
    """Construct shared application resources once; callers pass them explicitly.

    Effects:
        writes: creates the data root (mode 0o700) if it does not exist yet.
    Repeat:
        accumulates: each call returns a new lock registry, and two registries do not exclude
            each other; call once per application lifetime.
    Loops:
        none
    Concurrency:
        free
    Raises:
        OSError: the data root cannot be created.
    """
    return (
        Pipe
            .get(initial)
                .prepare_root(mode=0o700)
                    .prepare_store()
                        .prepare_locks()
                            .prepare_clock()
                                .materialize()
    )
