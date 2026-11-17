"""Rehearse notes/summarize and notes/summary through the root run with a typed fake of the
agent-runs port (tests/support/agent_runs.py): no agent process, no model, no network."""

from pathlib import Path

import pytest
from agent_runs import FakeAgentRuns

from backend_logic import run as backend
from backend_logic._shared.note_name.contracts import NoteValidationError
from backend_logic.notes.prepare.contracts import PrepareResources, Resources
from backend_logic.notes.save.contracts import AuthorId, SaveNote
from backend_logic.notes.summarize.contracts import DispatchSummary, NoteMissingError
from backend_logic.notes.summarize.pipeline import Pipe
from backend_logic.notes.summary.contracts import (
    AgentAnswerRejectedError,
    NoteSummary,
    ReadSummary,
    SummaryRunMissingError,
    SummaryState,
)


async def prepared(tmp_path: Path, author: str = "internal-author-7") -> Resources:
    resources = await backend.run(
        PrepareResources(data_root=tmp_path / "data", author_id=AuthorId(author))
    )
    await backend.run(
        SaveNote(
            name="trip",
            body="Book the train. Pack a coat.",
            author_id=resources.author_id,
            replace=False,
            expected_revision=None,
        ),
        resources=resources,
    )
    return resources


async def test_dispatch_hands_over_a_projection_of_the_stored_note(tmp_path: Path) -> None:
    resources, agents = await prepared(tmp_path), FakeAgentRuns()
    dispatched = await backend.run(DispatchSummary(name="trip"), resources=resources, agents=agents)

    (submission,) = agents.submissions
    assert submission.work == "note_summary"
    assert submission.tenant == "internal-author-7"
    # Privacy before the context: name and text only, never the author or the revision.
    assert dict(submission.payload) == {"name": "trip", "text": "Book the train. Pack a coat."}
    assert dispatched.name == "trip"
    assert dispatched.run_id in agents.runs


async def test_the_answer_is_read_and_admitted_once_the_run_completed(tmp_path: Path) -> None:
    resources, agents = await prepared(tmp_path), FakeAgentRuns()
    dispatched = await backend.run(DispatchSummary(name="trip"), resources=resources, agents=agents)
    request = ReadSummary(run_id=dispatched.run_id)

    queued = await backend.run(request, resources=resources, agents=agents)
    agents.answer_from_payload(dispatched.run_id)
    completed = await backend.run(request, resources=resources, agents=agents)

    assert queued == SummaryState(status="queued", summary=None, reason=None)
    assert completed == SummaryState(
        status="completed", summary=NoteSummary(text="trip: Book the train."), reason=None
    )
    assert agents.observed == [("internal-author-7", dispatched.run_id)] * 2


async def test_a_failed_run_reports_its_reason_and_no_summary(tmp_path: Path) -> None:
    resources, agents = await prepared(tmp_path), FakeAgentRuns()
    dispatched = await backend.run(DispatchSummary(name="trip"), resources=resources, agents=agents)
    agents.finish(dispatched.run_id, output=None, status="failed", reason="LIMIT_EXCEEDED")

    state = await backend.run(ReadSummary(dispatched.run_id), resources=resources, agents=agents)

    assert state == SummaryState(status="failed", summary=None, reason="LIMIT_EXCEEDED")


async def test_nothing_is_handed_over_for_a_bad_name_or_a_missing_note(tmp_path: Path) -> None:
    resources, agents = await prepared(tmp_path), FakeAgentRuns()
    with pytest.raises(NoteValidationError):
        await backend.run(DispatchSummary(name="../trip"), resources=resources, agents=agents)
    with pytest.raises(NoteMissingError):
        await backend.run(DispatchSummary(name="absent"), resources=resources, agents=agents)
    assert agents.submissions == []


async def test_an_unknown_run_and_another_tenants_run_look_the_same(tmp_path: Path) -> None:
    resources, agents = await prepared(tmp_path), FakeAgentRuns()
    dispatched = await backend.run(DispatchSummary(name="trip"), resources=resources, agents=agents)
    other = await backend.run(
        PrepareResources(data_root=tmp_path / "other", author_id=AuthorId("someone-else"))
    )
    for run_id, holder in (("no-such-run", resources), (dispatched.run_id, other)):
        with pytest.raises(SummaryRunMissingError):
            await backend.run(ReadSummary(run_id), resources=holder, agents=agents)


@pytest.mark.parametrize(
    "output",
    [
        None,
        "not json\n",
        '["summary"]\n',
        '{"summary": "x", "extra": 1}\n',
        '{"summary": "   "}\n',
        '{"summary": 3}\n',
        '{"summary": "%s"}' % ("x" * 601),
        '{"summary": "a", "summary": "b"}\n',
    ],
)
async def test_an_answer_against_the_contract_is_rejected_not_repaired(
    tmp_path: Path, output: str | None
) -> None:
    resources, agents = await prepared(tmp_path), FakeAgentRuns()
    dispatched = await backend.run(DispatchSummary(name="trip"), resources=resources, agents=agents)
    agents.finish(dispatched.run_id, output=output)

    with pytest.raises(AgentAnswerRejectedError):
        await backend.run(ReadSummary(dispatched.run_id), resources=resources, agents=agents)


async def test_the_submission_is_handed_over_once(tmp_path: Path) -> None:
    resources, agents = await prepared(tmp_path), FakeAgentRuns()
    pipe = (
        Pipe.get(DispatchSummary(name="trip"))
        .validate_name()
        .resolve_path(directory="notes", suffix=".json")
        .read_note(store=resources.store)
        .project_note()
        .prepare_submission(work="note_summary", tenant="t")
    )
    await pipe.submit(agents=agents, work="note_summary")
    with pytest.raises(RuntimeError, match="already handed over"):
        await pipe.submit(agents=agents, work="note_summary")
    assert len(agents.submissions) == 1
