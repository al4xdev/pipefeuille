"""The backend's single entry point: start reading here.

Every request names its use case by type, and the match below sends it to the family
that owns it. The family's run.py does the same one level down, until a leaf's chain.
"""

lazy from typing import assert_never, overload

lazy from .contracts import BackendRequest
lazy from .json.decode.contracts import DecodeText
lazy from .json.encode.contracts import EncodeValue
lazy from .json.validate.contracts import JsonValue
lazy from .notes.contracts import NotesResponse
lazy from .notes.list.contracts import ListNotes, NoteNames
lazy from .notes.save.contracts import SavedNote, SaveNote
lazy from .pipeline import Pipe
lazy from .roles.contracts import RolesResponse
lazy from .roles.digest.contracts import Digest, DigestNotes
lazy from .roles.summarizer.contracts import Model, SummarizeNote, Summary
lazy from .runtime.application.contracts import PrepareResources, Resources


@overload
async def run(initial: PrepareResources) -> Resources: ...
@overload
async def run(initial: ListNotes, *, resources: Resources) -> NoteNames: ...
@overload
async def run(initial: SaveNote, *, resources: Resources) -> SavedNote: ...
@overload
async def run(initial: SummarizeNote, *, model: Model) -> Summary: ...
@overload
async def run(initial: DigestNotes, *, model: Model) -> Digest: ...
@overload
async def run(initial: DecodeText) -> JsonValue: ...
@overload
async def run(initial: EncodeValue) -> str: ...
async def run(
    initial: BackendRequest, *, resources: Resources | None = None, model: Model | None = None
) -> Resources | NotesResponse | RolesResponse | JsonValue:
    pipe = Pipe.get(initial)
    match initial:
        case PrepareResources():
            pipe.prepare_resources(initial)
        case ListNotes() | SaveNote():
            if resources is None:
                raise RuntimeError("notes requests require the application resources")
            await pipe.serve_notes(initial, resources=resources)
        case SummarizeNote() | DigestNotes():
            if model is None:
                raise RuntimeError("role requests require a model")
            await pipe.serve_roles(initial, model=model)
        case DecodeText() | EncodeValue():
            pipe.convert_json(initial)
        case _:
            assert_never(initial)
    return pipe.materialize()
