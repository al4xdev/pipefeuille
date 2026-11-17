"""The agent-runs port's harness adapter against a stand-in of the harness server's two routes
(httpx.MockTransport): what it sends, and how every answer maps. No socket is opened."""

from collections.abc import Callable

import httpx
import pytest

from backend_logic import run as backend
from backend_logic._shared.agents.contracts import (
    AgentsUnavailableError,
    Observation,
    Submission,
    SubmissionTooLargeError,
)
from backend_logic._shared.agents.harness.contracts import (
    AGENTS,
    MAX_INPUT_BYTES,
    HarnessAgents,
    OpenHarness,
    escaped_size,
)
from backend_logic._shared.json.contracts import JsonValue
from backend_logic._shared.json.decode.contracts import DecodeText
from backend_logic._shared.json.decode.run import run as decoding
from backend_logic._shared.json.encode.contracts import EncodeValue
from backend_logic._shared.json.encode.run import run as encoding

RUN_ID = "0123abcd-0123-4567-89ab-0123456789ab"
type Handler = Callable[[httpx.Request], httpx.Response]


class Harness:
    """Records each request (route and decoded body) and answers with the handler's response."""

    def __init__(self, handler: Handler) -> None:
        self.requests: list[tuple[str, JsonValue]] = []
        self.handler = handler

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.url.path, decoding(DecodeText(request.content.decode()))))
        return self.handler(request)

    def agents(self) -> HarnessAgents:
        def write_json(value: JsonValue) -> str:
            return encoding(EncodeValue(value))

        def read_json(text: str) -> JsonValue:
            return decoding(DecodeText(text))

        return HarnessAgents(
            "http://harness.test",
            timeout=1.0,
            read_json=read_json,
            write_json=write_json,
            transport=httpx.MockTransport(self),
        )


def answering(status: int, content: bytes) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=content)

    return handler


SUBMISSION = Submission(work="note_summary", tenant="owner", payload={"name": "n", "text": "t"})


async def test_submit_dispatches_the_works_agent_and_returns_its_process_id() -> None:
    harness = Harness(answering(202, b'{"status": "queued", "process_id": "%s"}' % RUN_ID.encode()))
    run_id = await harness.agents().submit(SUBMISSION)
    assert run_id == RUN_ID
    assert harness.requests == [
        (
            "/dispatch",
            {"agent_name": "summarizer", "tenant_id": "owner", "input": {"name": "n", "text": "t"}},
        )
    ]
    assert AGENTS == {"note_summary": "summarizer"}


@pytest.mark.parametrize(
    ("status", "content"),
    [
        (500, b"{}"),
        (422, b'{"detail": []}'),
        (202, b"not json"),
        (202, b"[]"),
        (202, b'{"process_id": "not-a-uuid"}'),
        (202, b'{"process_id": "0123ABCD-0123-4567-89AB-0123456789AB"}'),
        (202, b"\xff"),
    ],
)
async def test_any_other_dispatch_answer_is_unavailable(status: int, content: bytes) -> None:
    with pytest.raises(AgentsUnavailableError):
        await Harness(answering(status, content)).agents().submit(SUBMISSION)


async def test_what_the_harness_would_refuse_is_never_sent() -> None:
    harness = Harness(answering(202, b"{}"))
    big = Submission(work="note_summary", tenant="owner", payload={"text": "x" * MAX_INPUT_BYTES})
    with pytest.raises(SubmissionTooLargeError):
        await harness.agents().submit(big)
    bad_tenant = Submission(work="note_summary", tenant="../etc", payload={})
    with pytest.raises(AgentsUnavailableError):
        await harness.agents().submit(bad_tenant)
    assert harness.requests == []


def test_the_size_is_counted_as_the_harness_encodes_the_argv() -> None:
    # json.dumps's default (ensure_ascii): é -> \\u00e9, € -> \\u20ac, 😀 -> a surrogate pair.
    for text, size in (("a", 1), ("é", 6), ("€", 6), ("😀", 12), ('"é😀"', 20)):
        assert escaped_size(text) == size, text


async def test_a_latin_payload_is_refused_at_its_escaped_size() -> None:
    harness = Harness(answering(202, b"{}"))
    # 25 000 é encode to 50 000 UTF-8 bytes but 150 000 escaped ones: past the cap.
    big = Submission(work="note_summary", tenant="owner", payload={"text": "é" * 25_000})
    with pytest.raises(SubmissionTooLargeError):
        await harness.agents().submit(big)
    assert harness.requests == []


async def test_a_harness_refusal_for_size_is_too_large() -> None:
    with pytest.raises(SubmissionTooLargeError):
        await Harness(answering(413, b'{"detail": "too large"}')).agents().submit(SUBMISSION)


async def test_observe_maps_the_status_answers() -> None:
    body = b'{"status": "failed", "process_id": "%s", "output": "", "reason": "LIMIT_EXCEEDED"}'
    harness = Harness(answering(200, body % RUN_ID.encode()))
    assert await harness.agents().observe("owner", RUN_ID) == Observation(
        status="failed", output="", reason="LIMIT_EXCEEDED"
    )
    assert harness.requests == [("/status", {"tenant_id": "owner", "process_id": RUN_ID})]
    missing = Harness(answering(404, b'{"detail": "process not found"}'))
    assert await missing.agents().observe("owner", RUN_ID) == Observation(None, None)


async def test_an_id_the_harness_cannot_know_is_not_asked_about() -> None:
    harness = Harness(answering(200, b"{}"))
    assert await harness.agents().observe("owner", "../etc") == Observation(None, None)
    assert await harness.agents().observe("a b", RUN_ID) == Observation(None, None)
    assert harness.requests == []


@pytest.mark.parametrize(
    "content",
    [
        b'{"status": "lost"}',
        b'{"status": "completed", "output": 3}',
        b'{"status": "failed", "reason": "NEW_REASON"}',
        b"[]",
    ],
)
async def test_an_unexpected_status_body_is_unavailable(content: bytes) -> None:
    with pytest.raises(AgentsUnavailableError):
        await Harness(answering(200, content)).agents().observe("owner", RUN_ID)


async def test_a_transport_failure_is_unavailable() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(AgentsUnavailableError, match="dispatch: ConnectError"):
        await Harness(refuse).agents().submit(SUBMISSION)


@pytest.mark.parametrize(
    "opening",
    [
        OpenHarness(base_url="ftp://127.0.0.1:8081", timeout_seconds=1.0),
        OpenHarness(base_url="http://", timeout_seconds=1.0),
        OpenHarness(base_url="http://127.0.0.1:8081/api", timeout_seconds=1.0),
        OpenHarness(base_url="http://127.0.0.1:8081?x=1", timeout_seconds=1.0),
        OpenHarness(base_url="http://127.0.0.1:8081", timeout_seconds=0.0),
    ],
)
async def test_opening_refuses_what_routes_cannot_be_appended_to(opening: OpenHarness) -> None:
    with pytest.raises(ValueError):
        await backend.run(opening)


async def test_opening_sends_nothing_and_returns_the_adapter() -> None:
    opened = await backend.run(OpenHarness(base_url="http://127.0.0.1:1/", timeout_seconds=1.0))
    assert isinstance(opened, HarnessAgents)
    assert opened.base_url == "http://127.0.0.1:1"
