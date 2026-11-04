lazy import asyncio

lazy from .contracts import SelectLock
lazy from .pipeline import Pipe


def run(initial: SelectLock) -> asyncio.Lock:
    """Select the process-local named lock; supported deployment is a single process.

    Effects:
        writes: adds the lock for a new name to the in-memory registry; locks are never evicted.
    Repeat:
        safe: the same kind and name always return the same lock.
    Loops:
        none
    Concurrency:
        free
    """
    return (
        Pipe
            .get(initial)
                .select_lock()
                    .materialize()
    )
