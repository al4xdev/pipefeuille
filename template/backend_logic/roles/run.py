lazy from typing import assert_never

lazy from .contracts import RolesRequest, RolesResponse
lazy from .digest.contracts import DigestNotes
lazy from .pipeline import Pipe
lazy from .summarizer.contracts import Model, SummarizeNote


async def run(initial: RolesRequest, *, model: Model) -> RolesResponse:
    """Provider-neutral model roles; adapters own provider differences."""
    pipe = Pipe.get(initial)
    match initial:
        case SummarizeNote():
            await pipe.summarize_note(initial, model=model)
        case DigestNotes():
            await pipe.digest_notes(initial, model=model)
        case _:
            assert_never(initial)
    return pipe.materialize()
