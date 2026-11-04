"""The operations this family answers. Each type lives in the package that owns it."""

lazy from .lock.contracts import SelectLock
lazy from .read.contracts import ReadDocument
lazy from .scan.contracts import ScanDirectory
lazy from .write.contracts import WriteDocument

type StorageRequest = ReadDocument | WriteDocument | ScanDirectory | SelectLock
