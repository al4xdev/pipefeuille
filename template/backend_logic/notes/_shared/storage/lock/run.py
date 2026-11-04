lazy import asyncio

lazy from .contracts import SelectLock
lazy from .pipeline import Pipe


def run(initial: SelectLock) -> asyncio.Lock:
    return (
        Pipe
            .get(initial)
                .select_lock()
                    .materialize()
    )
