lazy from typing import assert_never

lazy from .contracts import NotesRequest, NotesResponse
lazy from .list.contracts import ListNotes
lazy from .pipeline import Pipe
lazy from .prepare.contracts import PrepareResources, Resources
lazy from .save.contracts import SaveNote


async def run(initial: NotesRequest, *, resources: Resources | None) -> NotesResponse:
    """Example domain: user notes, used to demonstrate the package language."""
    pipe = Pipe.get(initial)
    match initial:
        case PrepareResources():
            pipe.prepare_resources(initial)
        case ListNotes():
            if resources is None:
                raise RuntimeError("listing notes requires the prepared resources")
            pipe.list_notes(initial, resources=resources)
        case SaveNote():
            if resources is None:
                raise RuntimeError("saving a note requires the prepared resources")
            await pipe.save_note(initial, resources=resources)
        case _:
            assert_never(initial)
    return pipe.materialize()
