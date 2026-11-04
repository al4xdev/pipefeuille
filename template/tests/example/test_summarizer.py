"""Rehearse the role through its real run with a typed model fake; no real inference."""

import json
from datetime import UTC, datetime

import pytest

from backend_logic._shared.json.contracts import JsonValue
from backend_logic._shared.note_name.contracts import NoteName
from backend_logic.notes.save.contracts import AuthorId, NoteRecord, Revision
from backend_logic.roles.summarizer.contracts import (
    ModelReply,
    ModelRequest,
    ProposedSummary,
    SummarizeNote,
    Summary,
    SummaryRejectedError,
)
from backend_logic.roles.summarizer.pipeline import Pipe
from backend_logic.roles.summarizer.run import run

NOTE = NoteRecord(
    schema_version=1,
    name=NoteName("trip"),
    body="Book the train. Pack a coat.",
    author_id=AuthorId("internal-author-7"),
    revision=Revision(1),
    updated_at=datetime(2026, 1, 1, tzinfo=UTC),
)


class EchoingModel:
    """Typed fake whose reply is derived from the request it received, not a constant."""

    def __init__(self, *, extra_sentences: int = 0) -> None:
        self.requests: list[ModelRequest] = []
        self.extra_sentences = extra_sentences

    async def complete(self, request: ModelRequest) -> ModelReply:
        self.requests.append(request)
        body = request.user.split("\n\n", 1)[1]
        sentences: list[JsonValue] = [
            part.strip() + "." for part in body.split(".") if part.strip()
        ]
        sentences += ["Extra."] * self.extra_sentences
        payload: JsonValue = {"sentences": sentences}
        return ModelReply(content=json.dumps(payload))


class FixedReplyModel:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls = 0

    async def complete(self, request: ModelRequest) -> ModelReply:
        self.calls += 1
        return ModelReply(content=self.content)


async def test_role_projects_before_prompting_and_admits_the_reply() -> None:
    model = EchoingModel()

    summary = await run(SummarizeNote(note=NOTE, language="pt-BR"), model=model)

    assert summary == Summary(sentences=("Book the train.", "Pack a coat."))
    [request] = model.requests
    assert request.output_tokens == 256
    assert request.response_mode == "structured"
    assert "pt-BR" in request.system
    # Privacy before context: the internal ID never reaches the model.
    assert "internal-author-7" not in request.system + request.user


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        '{"sentences": "one"}',
        '{"sentences": [1]}',
        '{"sentences": [], "x": 1}',
        # Hostile shapes must reject, not crash: duplicates, NaN, depth, lone surrogate.
        '{"sentences": [], "sentences": []}',
        '{"sentences": [NaN]}',
        "[" * 5000 + "]" * 5000,
        '{"sentences": ["\\ud800"]}',
    ],
)
async def test_contract_violations_reject_without_a_second_call(content: str) -> None:
    model = FixedReplyModel(content)
    with pytest.raises(SummaryRejectedError):
        await run(SummarizeNote(note=NOTE, language="en"), model=model)
    assert model.calls == 1


async def test_admission_limit_is_enforced_on_a_real_proposal() -> None:
    with pytest.raises(SummaryRejectedError, match="sentence count"):
        await run(SummarizeNote(note=NOTE, language="en"), model=EchoingModel(extra_sentences=2))


def test_middle_segment_starts_from_a_decoded_proposal() -> None:
    pipe = Pipe.get(SummarizeNote(note=NOTE, language="en"))
    pipe.container.proposal = ProposedSummary(sentences=("  Trimmed.  ",))

    assert pipe.admit_summary(max_sentences=3).materialize() == Summary(sentences=("Trimmed.",))
