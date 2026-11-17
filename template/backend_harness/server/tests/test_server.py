"""The harness server with the in-memory queue, a fake runner standing for app-agent, and
the pieces it is made of (agents.json, exit codes, stderr relay, usage from session logs).

Offline: nothing here starts dsh or calls a model. Run with the server's own project:

    cd backend_harness/server && uv run pytest
"""

import json
import os
import stat
import time
from collections.abc import Iterator
from compression import zstd
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server

TENANT = "t1"
UUID = "0123abcd-0123-4567-89ab-0123456789ab"

# Stands for app-agent: `run <agent> <id> <input>`. The input JSON says what to do:
# {"exit": N} exits N after writing a JSON line to stdout and one structured and one
# plain line to stderr; {"sleep": S} waits first.
FAKE_RUNNER = """#!/usr/bin/env python3
import json, sys, time
_, verb, agent, process_id, raw = sys.argv
order = json.loads(raw)
time.sleep(order.get("sleep", 0))
print(json.dumps({"summary": f"{agent} handled {order.get('text', '')}"}))
sys.stderr.write(json.dumps({"severity": "WARNING", "component": "app-limits", "event": "limit-reached"}) + "\\n")
sys.stderr.write("the model's private reasoning\\n")
sys.exit(order.get("exit", 0))
"""


@pytest.fixture
def harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    runner = tmp_path / "app-agent"
    runner.write_text(FAKE_RUNNER)
    runner.chmod(runner.stat().st_mode | stat.S_IXUSR)
    agents = tmp_path / "agents.json"
    agents.write_text(json.dumps({"summarizer": {"limits": {"max_attempts": 2}}}))
    monkeypatch.setattr(server, "RUNNER", str(runner))
    monkeypatch.setattr(server, "WORK", str(tmp_path / "work"))
    monkeypatch.setattr(server, "AGENTS_FILE", str(agents))
    monkeypatch.setenv("DSH_HOME", str(tmp_path / "dsh"))
    monkeypatch.delenv("APP_PG_DSN", raising=False)
    with TestClient(server.api) as client:
        yield client


def dispatch(client: TestClient, order: dict[str, object], tenant: str = TENANT) -> str:
    response = client.post("/dispatch", json={"agent_name": "summarizer", "tenant_id": tenant, "input": order})
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "queued"
    return str(body["process_id"])


def ended(client: TestClient, process_id: str, tenant: str = TENANT) -> dict[str, object]:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        response = client.post("/status", json={"tenant_id": tenant, "process_id": process_id})
        assert response.status_code == 200, response.text
        body: dict[str, object] = response.json()
        if body["status"] in ("completed", "failed"):
            return body
        time.sleep(0.05)
    raise AssertionError(f"{process_id} did not end")


def test_a_run_completes_with_its_stdout_as_output(harness: TestClient) -> None:
    process_id = dispatch(harness, {"text": "a note"})
    body = ended(harness, process_id)
    assert body["status"] == "completed"
    assert body["output"] == '{"summary": "summarizer handled a note"}\n'
    assert body["reason"] is None
    # No session log in the fake run: usage is unknown, so absent, not null.
    assert "usage" not in body


def test_exit_75_is_a_final_limit_failure_and_other_codes_plain_failures(harness: TestClient) -> None:
    limit = ended(harness, dispatch(harness, {"exit": 75}))
    assert (limit["status"], limit["reason"]) == ("failed", "LIMIT_EXCEEDED")
    plain = ended(harness, dispatch(harness, {"exit": 1}))
    assert (plain["status"], plain["reason"]) == ("failed", None)


def test_another_tenants_process_answers_like_a_missing_one(harness: TestClient) -> None:
    process_id = dispatch(harness, {"text": "x"})
    ended(harness, process_id)
    for tenant, pid in (("t2", process_id), (TENANT, UUID)):
        response = harness.post("/status", json={"tenant_id": tenant, "process_id": pid})
        assert response.status_code == 404
        assert response.json() == {"detail": "process not found"}


@pytest.mark.parametrize(
    "body",
    [
        {"agent_name": "bad-name", "tenant_id": TENANT, "input": {}},
        {"agent_name": "_shared", "tenant_id": TENANT, "input": {}},
        {"agent_name": "summarizer", "tenant_id": "../etc", "input": {}},
        {"agent_name": "summarizer", "tenant_id": "x" * 65, "input": {}},
        {"agent_name": "summarizer", "tenant_id": TENANT, "input": "not an object"},
    ],
)
def test_ids_that_would_become_bad_paths_are_refused(harness: TestClient, body: dict[str, object]) -> None:
    assert harness.post("/dispatch", json=body).status_code == 422


def test_a_runner_that_cannot_start_fails_the_run(harness: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "RUNNER", "/nonexistent/app-agent")
    body = ended(harness, dispatch(harness, {}))
    assert (body["status"], body["reason"]) == ("failed", "START_FAILED")


def test_only_structured_stderr_is_relayed_and_everything_lands_in_the_err_file(
    harness: TestClient, capfd: pytest.CaptureFixture[str]
) -> None:
    process_id = dispatch(harness, {"text": "x"})
    ended(harness, process_id)
    # The watcher records the outcome once the process exits; the relay drains in its
    # own thread, so give it a moment.
    err = Path(server.WORK) / TENANT / f"{process_id}.err"
    deadline = time.monotonic() + 5
    while "private reasoning" not in (err.read_text() if err.exists() else "") and time.monotonic() < deadline:
        time.sleep(0.05)
    assert "the model's private reasoning" in err.read_text()
    relayed = capfd.readouterr().err
    assert "private reasoning" not in relayed
    lines = [json.loads(line) for line in relayed.splitlines() if '"app-limits"' in line]
    assert lines == [
        {
            "severity": "WARNING",
            "component": "app-limits",
            "event": "limit-reached",
            "process_id": process_id,
            "message": "limit-reached",
        }
    ]


def test_cap_holds_the_rest_in_order(harness: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "CAP", 1)
    first = dispatch(harness, {"sleep": 0.5})
    second = dispatch(harness, {})
    status = harness.post("/status", json={"tenant_id": TENANT, "process_id": second}).json()
    assert status["status"] == "queued"
    assert ended(harness, first)["status"] == "completed"
    assert ended(harness, second)["status"] == "completed"


def test_agents_json_is_strict(tmp_path: Path) -> None:
    path = tmp_path / "agents.json"
    path.write_text(json.dumps({"a": {"limits": {"max_attempts": 3}}, "b_2": {"limits": {"max_attempts": 1}}}))
    assert server.load_max_attempts(str(path)) == {"a": 3, "b_2": 1}
    bad_files: list[object] = [
        {},
        [],
        {"a": {"limits": {"max_attempts": 0}}},
        {"a": {"limits": {"max_attempts": True}}},
        {"a": {"limits": {"max_attempts": "3"}}},
        {"a": {"limits": {}}},
        {"bad-name": {"limits": {"max_attempts": 1}}},
    ]
    for bad in bad_files:
        path.write_text(json.dumps(bad))
        with pytest.raises(ValueError):
            server.load_max_attempts(str(path))


def test_the_server_refuses_to_start_without_valid_agents_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "AGENTS_FILE", str(tmp_path / "missing.json"))
    with pytest.raises(FileNotFoundError), TestClient(server.api):
        pass


def test_outcome_of_exit_codes() -> None:
    assert server.outcome(0) == ("completed", None)
    assert server.outcome(75) == ("failed", "LIMIT_EXCEEDED")
    assert server.outcome(2) == ("failed", None)
    assert server.outcome(-15) == ("failed", None)


def test_structured_lines_need_severity_and_component() -> None:
    assert server.structured(b'{"severity": "ERROR", "component": "app-fs"}\n') == {
        "severity": "ERROR",
        "component": "app-fs",
    }
    for line in (b"plain text\n", b'{"severity": "ERROR"}\n', b'["severity", "component"]\n', b"{bad json\n"):
        assert server.structured(line) is None


# --- usage --------------------------------------------------------------------------

EVENTS = [
    {"type": "request/header", "data": {"header": {"config": {"model": "deepseek-flash"}}}},
    {"type": "assistant/message", "data": {"usage": {"inputTokens": 100, "outputTokens": 20, "cacheReadTokens": 5}}},
    {"type": "assistant/message", "data": {"usage": {"inputTokens": 50, "outputTokens": 10, "reasoningTokens": 7}}},
    # A failed attempt carries no usage; a bad count, a bool and a non-event add nothing.
    {"type": "assistant/attempt", "data": {"usage": {"inputTokens": 999}}},
    {"type": "assistant/message", "data": {"usage": {"inputTokens": -1, "outputTokens": True}}},
    {"type": "compaction/summary", "data": {"model": "deepseek-v4-pro", "usage": {"cacheWriteTokens": 3}}},
]


def lines() -> list[str]:
    return [json.dumps(event) for event in EVENTS] + ["not json", '{"type": "assistant/message"}']


def test_usage_sums_model_calls_and_names_models() -> None:
    assert server.sum_usage(lines()) == {
        "input_tokens": 150,
        "output_tokens": 30,
        "reasoning_tokens": 7,
        "cache_read_tokens": 5,
        "cache_write_tokens": 3,
        "models": ["deepseek-flash", "deepseek-v4-pro"],
        "model": None,
    }


def test_usage_merges_over_attempts_and_unknown_adds_nothing() -> None:
    one = server.sum_usage(lines()[:3])
    assert one["model"] == "deepseek-flash"
    assert server.merge_usage(None, None) is None
    assert server.merge_usage(None, one) == one
    assert server.merge_usage(one, None) == one
    both = server.merge_usage(one, one)
    assert both is not None
    assert (both["input_tokens"], both["models"], both["model"]) == (300, ["deepseek-flash"], "deepseek-flash")


def test_usage_is_read_from_the_runs_session_log_frame_by_frame(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server, "WORK", "/tmp/app-work")
    monkeypatch.setenv("DSH_HOME", str(tmp_path))
    folder = server.session_folder(TENANT, "summarizer", UUID)
    assert folder == os.path.join(str(tmp_path), "sessions", f"--tmp-app-work-{TENANT}-summarizer-{UUID}--")
    session = Path(folder) / "session-1"
    session.mkdir(parents=True)
    text = "\n".join(lines()).encode()
    # Two zstd frames, cut mid-line, as dsh's batched writes leave them.
    middle = len(text) // 2
    (session / server.SESSION_LOG).write_bytes(zstd.compress(text[:middle]) + zstd.compress(text[middle:]))
    assert server.read_usage(TENANT, "summarizer", UUID) == server.sum_usage(lines())
    (session / server.SESSION_LOG).write_bytes(b"no zstd here")
    assert server.read_usage(TENANT, "summarizer", UUID) is None
    assert server.read_usage(TENANT, "summarizer", "ffffffff-0123-4567-89ab-0123456789ab") is None
