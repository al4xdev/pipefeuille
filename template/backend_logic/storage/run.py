lazy import asyncio
lazy from typing import assert_never, overload

lazy from .contracts import StorageRequest
lazy from .lock.contracts import SelectLock
lazy from .pipeline import Pipe
lazy from .read.contracts import JsonRead, ReadDocument
lazy from .scan.contracts import ScanDirectory
lazy from .write.contracts import WriteDocument, WriteReceipt


@overload
def run(initial: ReadDocument) -> JsonRead: ...
@overload
def run(initial: WriteDocument) -> WriteReceipt: ...
@overload
def run(initial: ScanDirectory) -> tuple[str, ...]: ...
@overload
def run(initial: SelectLock) -> asyncio.Lock: ...
def run(initial: StorageRequest) -> JsonRead | WriteReceipt | tuple[str, ...] | asyncio.Lock:
    pipe = Pipe.get(initial)
    match initial:
        case ReadDocument():
            pipe.read_document(initial)
        case WriteDocument():
            pipe.write_document(initial)
        case ScanDirectory():
            pipe.scan_directory(initial)
        case SelectLock():
            pipe.select_lock(initial)
        case _:
            assert_never(initial)
    return pipe.materialize()
