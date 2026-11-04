lazy import asyncio
lazy from typing import Self

lazy from .container import Container
lazy from .contracts import StorageRequest
lazy from .lock import run as locking
lazy from .lock.contracts import SelectLock
lazy from .read import run as reading
lazy from .read.contracts import JsonRead, ReadDocument
lazy from .scan import run as scanning
lazy from .scan.contracts import ScanDirectory
lazy from .write import run as writing
lazy from .write.contracts import WriteDocument, WriteReceipt


class Pipe:
    def __init__(self) -> None:
        self.container = Container()

    @classmethod
    def get(cls, initial: StorageRequest) -> Self:
        """Set input unchanged; run chooses the branch."""
        pipe = cls()
        pipe.container.input = initial
        return pipe

    def read_document(self, request: ReadDocument) -> Self:
        """Set read (Found or Missing) through the read child. Corruption propagates."""
        self.container.read = reading.run(request)
        return self

    def write_document(self, request: WriteDocument) -> Self:
        """Set receipt through the write child; AtomicWriteError propagates with its receipt."""
        self.container.receipt = writing.run(request)
        return self

    def scan_directory(self, request: ScanDirectory) -> Self:
        """Set files through the scan child. Read-only."""
        self.container.files = scanning.run(request)
        return self

    def select_lock(self, request: SelectLock) -> Self:
        """Set the unacquired named lock through the lock child."""
        self.container.lock = locking.run(request)
        return self

    def materialize(self) -> JsonRead | WriteReceipt | tuple[str, ...] | asyncio.Lock:
        """Require exactly the branch that ran; return its product."""
        if self.container.read is not None:
            return self.container.read
        if self.container.receipt is not None:
            return self.container.receipt
        if self.container.files is not None:
            return self.container.files
        if self.container.lock is not None:
            return self.container.lock
        raise RuntimeError("a storage branch must run before materialize")
