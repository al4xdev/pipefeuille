lazy from dataclasses import dataclass
lazy from enum import StrEnum
lazy from pathlib import Path
lazy from typing import Literal

lazy from backend_logic.json.validate.contracts import JsonValue

lazy from ..path.contracts import FileStore

# Where a publication stopped, in order; recovery reads it together with the receipt status.
type WritePhase = Literal[
    "serialize", "prepare", "write", "file_fsync", "replace", "directory_fsync"
]


@dataclass(frozen=True)
class WriteDocument:
    """One publication. Never offload it to a thread under an async lock: cancelling the
    coroutine releases the lock but does not stop the filesystem effects."""

    store: FileStore
    relative: str
    value: JsonValue


class PublicationStatus(StrEnum):
    NOT_PUBLISHED = "not_published"
    PUBLISHED_NOT_DURABLE = "published_not_durable"
    DURABLE = "durable"


@dataclass(frozen=True)
class WriteReceipt:
    path: Path
    status: PublicationStatus
    size_bytes: int | None


class AtomicWriteError(OSError):
    """Publication failed; inspect receipt before deciding recovery.

    NOT_PUBLISHED means the target was not replaced, not that no effects occurred:
    parent directories may have been created. PUBLISHED_NOT_DURABLE means
    the new bytes are visible but crash durability is unconfirmed; never treat it
    as rollback. The underlying exception is retained as __cause__.
    """

    def __init__(self, receipt: WriteReceipt, phase: WritePhase) -> None:
        self.receipt = receipt
        self.phase: WritePhase = phase
        super().__init__(f"Atomic write failed during {phase}: {receipt.status.value}")
