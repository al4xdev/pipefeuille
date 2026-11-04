lazy import asyncio
lazy from dataclasses import dataclass

lazy from .contracts import StorageRequest
lazy from .read.contracts import JsonRead
lazy from .write.contracts import WriteReceipt


@dataclass
class Container:
    input: StorageRequest | None = None
    read: JsonRead | None = None
    receipt: WriteReceipt | None = None
    files: tuple[str, ...] | None = None
    lock: asyncio.Lock | None = None
