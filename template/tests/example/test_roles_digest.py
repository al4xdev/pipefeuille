"""Rehearse the parallel role through its real run with typed model fakes; no real inference."""

import asyncio
import json
from datetime import UTC, datetime

import pytest

from backend_logic._shared.json.contracts import JsonValue
from backend_logic._shared.note_name.contracts import NoteName
from backend_logic.notes.save.contracts import AuthorId, NoteRecord, Revision
from backend_logic.roles.digest.contracts import Digest, DigestNotes, DigestRejectedError
from backend_logic.roles.digest.run import run
from backend_logic.roles.summarizer.contracts import (
    ModelReply,
    ModelRequest,
    Summary,
    SummaryRejectedError,
)


def note(name: str, body: str) -> NoteRecord:
    return NoteRecord(
        schema_version=1,
        name=NoteName(name),
        body=body,
        author_id=AuthorId("internal-author-7"),
        revision=Revision(1),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def title_of(request: ModelRequest) -> str:
    return request.user.split("\n\n", 1)[0].removeprefix("Title: ")


def reply_with(text: str) -> ModelReply:
    payload: JsonValue = {"sentences": [text]}
    return ModelReply(content=json.dumps(payload))


class SecondFinishesFirstModel:
    """'first' answers only after 'second' has answered: sequential calls would deadlock."""

    def __init__(self) -> None:
        self.second_done = asyncio.Event()
        self.finished: list[str] = []

    async def complete(self, request: ModelRequest) -> ModelReply:
        title = title_of(request)
        if title == "first":
            await self.second_done.wait()
        self.finished.append(title)
        if title == "second":
            self.second_done.set()
        return reply_with(f"About {title}.")


class OneBadReplyModel:
    """'bad' replies with a contract violation while 'slow' is still waiting."""

    def __init__(self) -> None:
        self.cancelled: list[str] = []

    async def complete(self, request: ModelRequest) -> ModelReply:
        title = title_of(request)
        if title == "bad":
            return ModelReply(content="not json")
        try:
            await asyncio.Event().wait()  # never set: only cancellation ends it
        except asyncio.CancelledError:
            self.cancelled.append(title)
            raise
        return reply_with("unreachable")


class CountingModel:
    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, request: ModelRequest) -> ModelReply:
        self.calls += 1
        return reply_with("Done.")


async def test_calls_run_concurrently_and_integrate_in_request_order() -> None:
    model = SecondFinishesFirstModel()
    notes = (note("first", "One."), note("second", "Two."))

    async with asyncio.timeout(1):
        digest = await run(DigestNotes(notes=notes, language="en"), model=model)

    assert model.finished == ["second", "first"]
    # Completion order was reversed; the digest still follows the notes as given.
    assert digest == Digest(
        summaries=(Summary(sentences=("About first.",)), Summary(sentences=("About second.",)))
    )


async def test_one_rejection_cancels_the_rest_and_returns_no_partial_digest() -> None:
    model = OneBadReplyModel()
    notes = (note("slow", "Wait."), note("bad", "Fail."))

    # The timeout turns a policy that waits for every call (e.g. gather) into a failure, not a hang.
    with pytest.raises(ExceptionGroup) as raised:
        async with asyncio.timeout(1):
            await run(DigestNotes(notes=notes, language="en"), model=model)

    assert raised.group_contains(SummaryRejectedError)
    assert model.cancelled == ["slow"]


@pytest.mark.parametrize(
    "notes",
    [
        (),
        tuple(note(f"n{index}", "x") for index in range(9)),
        (note("same", "a"), note("same", "b")),
    ],
    ids=["empty", "over-budget", "duplicate"],
)
async def test_invalid_requests_reject_before_any_model_call(notes: tuple[NoteRecord, ...]) -> None:
    model = CountingModel()

    with pytest.raises(DigestRejectedError):
        await run(DigestNotes(notes=notes, language="en"), model=model)

    assert model.calls == 0
