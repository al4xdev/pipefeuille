"""PgQueue against a real, disposable Postgres. Skipped unless APP_TEST_PG holds a libpq
connection string to a database these tests may write (they create and drop the schema
app_harness in it). E.g., with the local container of `docker.sh --pg` and PG_PORT=55432:

    APP_TEST_PG='host=127.0.0.1 port=55432 dbname=app user=postgres password=app-local' uv run pytest
"""

import os
import uuid
from collections.abc import Iterator

import pytest

import server

DSN = os.environ.get("APP_TEST_PG")
pytestmark = pytest.mark.skipif(not DSN, reason="APP_TEST_PG is not set (no disposable Postgres)")


def request(agent: str = "summarizer") -> server.DispatchRequest:
    return server.DispatchRequest(agent_name=agent, tenant_id="t1", input={"text": "a note"})


@pytest.fixture
def queue() -> Iterator[server.PgQueue]:
    assert DSN is not None
    made = server.PgQueue(DSN, {"summarizer": 2})
    with made.pool.connection() as conn:
        conn.execute(f"TRUNCATE {made.table}")
    server.STOP.clear()
    yield made
    with made.pool.connection() as conn:
        conn.execute(f"DROP SCHEMA {server.SCHEMA} CASCADE")
    made.close()


def test_a_row_goes_queued_running_completed_with_its_output(queue: server.PgQueue) -> None:
    pid = str(uuid.uuid4())
    queue.enqueue(pid, request())
    assert queue.get(pid) == {"tenant_id": "t1", "status": "queued", "output": None, "reason": None, "usage": None}
    claimed = queue.claim()
    assert claimed is not None
    assert (claimed[0], claimed[1].input, claimed[2]) == (pid, {"text": "a note"}, 1)
    assert queue.claim() is None  # nothing else queued
    usage = server.with_models({**server.zero_usage(), "input_tokens": 10}, ["deepseek-flash"])
    queue.finish(pid, 1, "completed", output='{"summary": "s"}\n', usage=usage)
    row = queue.get(pid)
    assert row is not None
    assert (row["status"], row["output"], row["usage"]["input_tokens"]) == ("completed", '{"summary": "s"}\n', 10)


def test_a_dead_run_is_requeued_then_fails_at_max_attempts(queue: server.PgQueue) -> None:
    pid = str(uuid.uuid4())
    queue.enqueue(pid, request())
    for attempt in (1, 2):
        claimed = queue.claim()
        assert claimed is not None and claimed[2] == attempt
        # A fresh instance claimed it before (tried): forget it so this instance may again.
        queue.tried.clear()
        queue.mine.clear()
        with queue.pool.connection() as conn:
            conn.execute(f"UPDATE {queue.table} SET heartbeat_at = now() - interval '1 hour'")
        queue.reap()
    row = queue.get(pid)
    assert row is not None
    assert (row["status"], row["reason"]) == ("failed", "ATTEMPTS_EXHAUSTED")


def test_a_write_fenced_by_another_attempt_changes_nothing(queue: server.PgQueue) -> None:
    pid = str(uuid.uuid4())
    queue.enqueue(pid, request())
    assert queue.claim() is not None
    queue.finish(pid, 7, "completed", output="late")  # not this row's attempt
    row = queue.get(pid)
    assert row is not None and row["status"] == "running"


def test_get_refuses_what_is_no_uuid(queue: server.PgQueue) -> None:
    assert queue.get("not-a-uuid") is None
    assert queue.get(str(uuid.uuid4())) is None
