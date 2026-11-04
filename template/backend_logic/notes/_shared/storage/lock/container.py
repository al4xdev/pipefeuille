lazy import asyncio
lazy from dataclasses import dataclass

lazy from .contracts import SelectLock


@dataclass
class Container:
    input: SelectLock | None = None
    lock: asyncio.Lock | None = None
