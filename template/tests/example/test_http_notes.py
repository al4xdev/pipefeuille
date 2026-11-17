"""Isolated HTTP boundary: routes adapt, the logical runs decide."""

from pathlib import Path

import pytest
from agent_runs import FakeAgentRuns
from wire_client import serving

from http_adapter.application import create_app


async def test_app_construction_touches_no_disk_until_the_lifespan_starts(tmp_path: Path) -> None:
    app = create_app(data_root=tmp_path / "data", agents=FakeAgentRuns())
    assert not (tmp_path / "data").exists()
    async with serving(app):
        assert (tmp_path / "data").is_dir()


async def test_http_round_trip_maps_logical_errors_and_hides_internal_ids(
    tmp_path: Path,
) -> None:
    async with serving(create_app(data_root=tmp_path / "data", agents=FakeAgentRuns())) as client:
        created = await client.put("/notes/todo", b'{"body": "write the guide"}')
        duplicate = await client.put("/notes/todo", b'{"body": "again"}')
        invalid = await client.put("/notes/bad name", b'{"body": "x"}')
        listed = await client.get("/notes")

    assert created.status == 200
    assert isinstance(created.body, dict)
    assert created.body["revision"] == 1
    assert "author_id" not in created.body
    assert (duplicate.status, duplicate.detail()) == (409, "note_exists")
    assert (invalid.status, invalid.detail()) == (422, "invalid_name")
    assert listed.body == {"names": ["todo"]}


@pytest.mark.parametrize(
    "content",
    [
        b"not json",
        b'["body"]',
        b'{"body": 1}',
        b'{"body": "x", "replace": "yes"}',
        b'{"body": "x", "expected_revision": true}',
        b'{"body": "x", "author_id": "intruder"}',
        b'{"body": "first", "body": "second"}',
        b'{"body": "\\ud800"}',
        b'{"body": "\xff"}',
        b"[" * 5000 + b"]" * 5000,
    ],
)
async def test_malformed_wire_body_is_rejected_before_the_logical_run(
    tmp_path: Path, content: bytes
) -> None:
    async with serving(create_app(data_root=tmp_path / "data", agents=FakeAgentRuns())) as client:
        response = await client.put("/notes/todo", content)

        assert (response.status, response.detail()) == (422, "invalid_body")
        assert (await client.get("/notes")).body == {"names": []}


async def test_http_summary_flow_dispatches_reads_and_maps_errors(tmp_path: Path) -> None:
    agents = FakeAgentRuns()
    async with serving(create_app(data_root=tmp_path / "data", agents=agents)) as client:
        await client.put("/notes/todo", b'{"body": "Write the guide. Then rest."}')
        dispatched = await client.post("/notes/todo/summary")
        missing = await client.post("/notes/absent/summary")
        invalid = await client.post("/notes/bad name/summary")
        assert isinstance(dispatched.body, dict)
        run_id = dispatched.body["run_id"]
        assert isinstance(run_id, str)
        queued = await client.get(f"/summaries/{run_id}")
        agents.answer_from_payload(run_id)
        completed = await client.get(f"/summaries/{run_id}")
        unknown = await client.get("/summaries/no-such-run")
        agents.finish(run_id, output="not json")
        rejected = await client.get(f"/summaries/{run_id}")

    assert (dispatched.status, dispatched.body["name"]) == (202, "todo")
    assert (missing.status, missing.detail()) == (404, "note_missing")
    assert (invalid.status, invalid.detail()) == (422, "invalid_name")
    assert queued.body == {"status": "queued", "summary": None, "reason": None}
    assert completed.body == {
        "status": "completed",
        "summary": "todo: Write the guide.",
        "reason": None,
    }
    assert (unknown.status, unknown.detail()) == (404, "summary_run_missing")
    assert (rejected.status, rejected.detail()) == (502, "summary_rejected")
    assert len(agents.submissions) == 1
