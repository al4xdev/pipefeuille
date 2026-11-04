lazy import asyncio
lazy from typing import Self

lazy from .container import Container
lazy from .contracts import SelectLock


class Pipe:
    def __init__(self) -> None:
        self.container = Container()

    @classmethod
    def get(cls, initial: SelectLock) -> Self:
        """Set input unchanged; nothing is selected yet."""
        pipe = cls()
        pipe.container.input = initial
        return pipe

    def select_lock(self) -> Self:
        """Require input; set the registry's lock for (kind, name), adding it on first use.

        Does not acquire it: the caller's `async with` keeps the critical section visible.
        """
        if self.container.input is None:
            raise RuntimeError("lock selection requires input")
        initial = self.container.input
        key = (initial.kind, initial.name)
        self.container.lock = initial.registry.locks.setdefault(key, asyncio.Lock())
        return self

    def materialize(self) -> asyncio.Lock:
        """Require lock; return it unacquired."""
        if self.container.lock is None:
            raise RuntimeError("selected lock is required")
        return self.container.lock
