lazy from .contracts import WriteDocument, WriteReceipt
lazy from .pipeline import Pipe


def run(initial: WriteDocument) -> WriteReceipt:
    """Publish one JSON document atomically, with an explicit durability receipt.

    No multi-file transaction, automatic retry or rollback after publication.

    Effects:
        writes: one file beneath the store root, by temporary file, fsync and rename.
    Repeat:
        overwrites: the last publication wins.
    Loops:
        none
    Concurrency:
        caller-locks: never acquires locks; the caller holds its named lock across
            read, modify and write.
    Raises:
        AtomicWriteError: serialization or publication failed; carries the receipt and phase.
        ValueError: the path leaves the store root.
    """
    return (
        Pipe
            .get(initial)
                .resolve_path()
                    .encode_payload()
                        .publish_atomically(mode=0o700)
                            .materialize()
    )
