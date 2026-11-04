lazy from dataclasses import dataclass
lazy from pathlib import Path

lazy from .contracts import WriteDocument, WriteReceipt


@dataclass
class Container:
    input: WriteDocument | None = None
    path: Path | None = None
    payload: bytes | None = None
    receipt: WriteReceipt | None = None
