"""Translate HTTP into public note requests and logical results into JSON."""

lazy from dataclasses import dataclass

lazy from fastapi import APIRouter, HTTPException, Request
lazy from fastapi.responses import JSONResponse

lazy from backend_logic import run as backend
lazy from backend_logic._shared.json.contracts import JsonValue
lazy from backend_logic._shared.json.decode.contracts import DecodeText
lazy from backend_logic._shared.note_name.contracts import NoteValidationError
lazy from backend_logic.notes.list.contracts import ListNotes
lazy from backend_logic.notes.save.contracts import NoteConflictError, Revision, SaveNote

lazy from ..lifetime import ResourceSlot


@dataclass(frozen=True)
class NoteSubmission:
    """Wire body only; the logical save still owns every domain admission."""

    body: str
    replace: bool
    expected_revision: Revision | None


async def decode_submission(raw: bytes) -> NoteSubmission:
    # No pydantic: its models carry Any into the contract. The backend's shared strict json
    # owns JSON policy (duplicates, NaN, surrogates, depth); this adapter owns wire shape.
    try:
        value = await backend.run(DecodeText(raw.decode("utf-8")))
    except ValueError:
        raise HTTPException(status_code=422, detail="invalid_body") from None
    if not isinstance(value, dict) or not set(value) <= {"body", "replace", "expected_revision"}:
        raise HTTPException(status_code=422, detail="invalid_body")
    body = value.get("body")
    replace = value.get("replace", False)
    expected_revision = value.get("expected_revision")
    if not isinstance(body, str) or type(replace) is not bool:
        raise HTTPException(status_code=422, detail="invalid_body")
    if expected_revision is not None and type(expected_revision) is not int:
        raise HTTPException(status_code=422, detail="invalid_body")
    # Revision only names the client's claim; save compares it with the stored one.
    revision = None if expected_revision is None else Revision(expected_revision)
    return NoteSubmission(body=body, replace=replace, expected_revision=revision)


def build_router(*, slot: ResourceSlot) -> APIRouter:
    """Resources and the server-side author identity come from the application owner."""

    async def list_notes() -> JSONResponse:
        listed = await backend.run(ListNotes(), resources=slot.require())
        body: JsonValue = {"names": list(listed.names)}
        return JSONResponse(body)

    async def save_note(name: str, request: Request) -> JSONResponse:
        submission = await decode_submission(await request.body())
        resources = slot.require()
        try:
            saved = await backend.run(
                SaveNote(
                    name=name,
                    body=submission.body,
                    author_id=resources.author_id,
                    replace=submission.replace,
                    expected_revision=submission.expected_revision,
                ),
                resources=resources,
            )
        except NoteValidationError as error:
            raise HTTPException(status_code=422, detail=error.code) from None
        except NoteConflictError as error:
            raise HTTPException(status_code=409, detail=error.code) from None
        # author_id is internal routing; it does not leave the server.
        body: JsonValue = {
            "name": saved.record.name,
            "body": saved.record.body,
            "revision": saved.record.revision,
            "updated_at": saved.record.updated_at.isoformat(),
        }
        return JSONResponse(body)

    # add_api_route instead of @router.get: FastAPI's decorators are typed with Any, and the
    # mypy gate keeps Any out of every expression (§6).
    router = APIRouter()
    router.add_api_route("/notes", list_notes, methods=["GET"])
    router.add_api_route("/notes/{name}", save_note, methods=["PUT"])
    return router
