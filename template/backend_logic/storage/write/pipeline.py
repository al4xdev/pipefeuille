lazy import os
lazy import tempfile
lazy from pathlib import Path
lazy from typing import Self

lazy from backend_logic.json import run as json_text
lazy from backend_logic.json.encode.contracts import EncodeValue

lazy from ..path import run as locating
lazy from ..path.contracts import ResolvePath
lazy from .container import Container
lazy from .contracts import (
    AtomicWriteError,
    PublicationStatus,
    WriteDocument,
    WritePhase,
    WriteReceipt,
)


class Pipe:
    def __init__(self) -> None:
        self.container = Container()

    @classmethod
    def get(cls, initial: WriteDocument) -> Self:
        """Set input unchanged; nothing is serialized or written yet."""
        pipe = cls()
        pipe.container.input = initial
        return pipe

    def resolve_path(self) -> Self:
        """Require input; set path confined by the shared path sibling. No I/O."""
        if self.container.input is None:
            raise RuntimeError("document write requires input")
        initial = self.container.input
        self.container.path = locating.run(ResolvePath(initial.store, initial.relative))
        return self

    def encode_payload(self) -> Self:
        """Require input and path; set UTF-8 payload through strict JSON. No I/O.

        A value decode would reject fails here as AtomicWriteError(NOT_PUBLISHED, "serialize").
        """
        if self.container.input is None or self.container.path is None:
            raise RuntimeError("payload encoding requires input and path")
        try:
            text = json_text.run(EncodeValue(self.container.input.value))
        except (TypeError, ValueError) as error:
            receipt = WriteReceipt(self.container.path, PublicationStatus.NOT_PUBLISHED, None)
            raise AtomicWriteError(receipt, "serialize") from error
        self.container.payload = text.encode("utf-8")
        return self

    def publish_atomically(self, *, mode: int) -> Self:
        """Require path/payload; publish once via same-directory temp file, fsync and replace.

        Set receipt. On failure raise AtomicWriteError carrying the receipt of what is
        visible: after replace the bytes are published even if the directory fsync fails.
        """
        path, payload = self.container.path, self.container.payload
        if path is None or payload is None:
            raise RuntimeError("publication requires path and payload")
        if self.container.receipt is not None:
            raise RuntimeError("publication was already attempted")
        status = PublicationStatus.NOT_PUBLISHED
        phase: WritePhase = "prepare"
        temporary: Path | None = None
        try:
            path.parent.mkdir(mode=mode, parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(prefix=".atomic-", suffix=".tmp", dir=path.parent)
            temporary = Path(name)
            with os.fdopen(fd, "wb") as stream:
                phase = "write"
                stream.write(payload)
                stream.flush()
                phase = "file_fsync"
                os.fsync(stream.fileno())
            phase = "replace"
            os.replace(temporary, path)
            temporary = None
            status = PublicationStatus.PUBLISHED_NOT_DURABLE
            phase = "directory_fsync"
            directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            status = PublicationStatus.DURABLE
        except Exception as error:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            published_size = None if status is PublicationStatus.NOT_PUBLISHED else len(payload)
            self.container.receipt = WriteReceipt(path, status, published_size)
            raise AtomicWriteError(self.container.receipt, phase) from error
        self.container.receipt = WriteReceipt(path, status, len(payload))
        return self

    def materialize(self) -> WriteReceipt:
        """Require receipt; return it. Only a successful publication reaches here."""
        if self.container.receipt is None:
            raise RuntimeError("publication receipt is required")
        return self.container.receipt
