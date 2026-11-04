lazy import asyncio
lazy from dataclasses import dataclass, field


@dataclass
class LockRegistry:
    """One owner constructs this per application lifetime and passes it explicitly.

    Locks are never evicted: a lock dropped while held would let a second writer in.
    """

    locks: dict[tuple[str, str], asyncio.Lock] = field(default_factory=dict)


@dataclass(frozen=True)
class SelectLock:
    """Not reentrant: a parent that holds the lock must call children that declare
    "requires lock already held", never children that reacquire it."""

    registry: LockRegistry
    kind: str
    name: str
