"""The climb: every use case enters at backend_logic/run.py and reaches its family."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from backend_logic import run as backend
from backend_logic.json.decode.contracts import DecodeText
from backend_logic.json.encode.contracts import EncodeValue
from backend_logic.notes.list.contracts import ListNotes, NoteNames
from backend_logic.notes.name.contracts import NoteName
from backend_logic.notes.save.contracts import AuthorId, NoteRecord, Revision, SaveNote
from backend_logic.roles.digest.contracts import Digest, DigestNotes
from backend_logic.roles.summarizer.contracts import (
    ModelReply,
    ModelRequest,
    SummarizeNote,
    Summary,
)
from backend_logic.runtime.application.contracts import PrepareResources


class OneSentenceModel:
    async def complete(self, request: ModelRequest) -> ModelReply:
        return ModelReply(content=json.dumps({"sentences": ["Done."]}))


async def test_each_family_is_reached_from_the_root(tmp_path: Path) -> None:
    resources = await backend.run(
        PrepareResources(data_root=tmp_path / "data", author_id=AuthorId("owner"))
    )
    saved = await backend.run(
        SaveNote(
            name="todo",
            body="x",
            author_id=resources.author_id,
            replace=False,
            expected_revision=None,
        ),
        resources=resources,
    )
    listed = await backend.run(ListNotes(), resources=resources)
    summary = await backend.run(
        SummarizeNote(note=saved.record, language="en"), model=OneSentenceModel()
    )
    digest = await backend.run(
        DigestNotes(notes=(saved.record,), language="en"), model=OneSentenceModel()
    )

    assert saved.record.revision == 1
    assert listed == NoteNames(names=(NoteName("todo"),))
    assert summary == Summary(sentences=("Done.",))
    assert digest == Digest(summaries=(Summary(sentences=("Done.",)),))
    assert await backend.run(EncodeValue([1])) == "[\n  1\n]\n"


async def test_root_keeps_json_null_distinct_from_a_branch_not_run() -> None:
    assert await backend.run(DecodeText("null")) is None


async def test_missing_dependency_fails_loudly_instead_of_guessing() -> None:
    note = NoteRecord(
        schema_version=1,
        name=NoteName("n"),
        body="b",
        author_id=AuthorId("a"),
        revision=Revision(1),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    # Overloads make these calls type errors; the runtime guard covers untyped callers.
    with pytest.raises(RuntimeError, match="resources"):
        await backend.run(ListNotes())  # type: ignore[call-overload]
    with pytest.raises(RuntimeError, match="model"):
        await backend.run(SummarizeNote(note=note, language="en"))  # type: ignore[call-overload]
