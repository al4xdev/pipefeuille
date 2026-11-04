lazy from .contracts import WriteDocument, WriteReceipt
lazy from .pipeline import Pipe


def run(initial: WriteDocument) -> WriteReceipt:
    return (
        Pipe
            .get(initial)
                .resolve_path()
                    .encode_payload()
                        .publish_atomically(mode=0o700)
                            .materialize()
    )
