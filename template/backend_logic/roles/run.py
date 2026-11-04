lazy from typing import assert_never, overload

lazy from .contracts import RolesRequest, RolesResponse
lazy from .digest.contracts import Digest, DigestNotes
lazy from .pipeline import Pipe
lazy from .summarizer.contracts import Model, SummarizeNote, Summary


@overload
async def run(initial: SummarizeNote, *, model: Model) -> Summary: ...
@overload
async def run(initial: DigestNotes, *, model: Model) -> Digest: ...
async def run(initial: RolesRequest, *, model: Model) -> RolesResponse:
    pipe = Pipe.get(initial)
    match initial:
        case SummarizeNote():
            await pipe.summarize_note(initial, model=model)
        case DigestNotes():
            await pipe.digest_notes(initial, model=model)
        case _:
            assert_never(initial)
    return pipe.materialize()
