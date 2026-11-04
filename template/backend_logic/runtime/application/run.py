lazy from .contracts import PrepareResources, Resources
lazy from .pipeline import Pipe


def run(initial: PrepareResources) -> Resources:
    return (
        Pipe
            .get(initial)
                .prepare_root(mode=0o700)
                    .prepare_store()
                        .prepare_locks()
                            .prepare_clock()
                                .materialize()
    )
