"""The agent-runs port on the harness server (backend_harness/server), over HTTP.

The only module of the logic that knows the harness, its agents and its HTTP client (httpx, a
declared dependency). The harness listens on loopback, inside the same image as the HTTP
application; its process id is the run id, from dispatch to status. A submission is never
retried here: the harness has no idempotency key, so a retry after a lost answer would run
the work twice.

HarnessAgents gets the strict JSON reader and writer from this package's run (OpenHarness):
it never parses with the client's own JSON, and this module never calls its own run.
"""

lazy import re
lazy from collections.abc import Callable
lazy from dataclasses import dataclass
lazy from typing import Literal

lazy import httpx

lazy from backend_logic._shared.agents.contracts import (
    AgentsUnavailableError,
    AgentWork,
    Observation,
    RunId,
    RunReason,
    Submission,
    SubmissionTooLargeError,
)
lazy from backend_logic._shared.json.contracts import JsonValue

# Work -> harness agent (backend_harness/agents/<name>). The works name what is done, never
# who does it; this table is where the two meet. tests/support/architecture.py reads it to
# draw the `dispatches` edge of each agent: keep it one dict literal.
AGENTS: dict[AgentWork, str] = {
    "note_summary": "summarizer",
}

# The harness hands `input` to dsh as ONE argv string (json.dumps, ASCII escapes), and Linux
# caps one argument at 128 KiB (MAX_ARG_STRLEN). The harness server refuses more than this at
# /dispatch (413, its own MAX_INPUT_BYTES); refused here first, counted the same way.
MAX_INPUT_BYTES = 120_000


def escaped_size(text: str) -> int:
    """The bytes of a JSON text once its non-ASCII characters are escaped, as json.dumps
    does by default: `\\uXXXX` (6), or a surrogate pair of them (12) past the BMP."""
    return sum(1 if ord(char) < 0x80 else 6 if ord(char) <= 0xFFFF else 12 for char in text)


# The harness's grammar: its ids are lowercase uuid4 strings, and a tenant becomes a path
# segment of the run's workspace. Anything else would be refused there or never found again.
PROCESS_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
TENANT = re.compile(r"[A-Za-z0-9_-]{1,64}")
STATUSES = ("queued", "running", "completed", "failed")
REASONS: tuple[RunReason, ...] = (
    "LIMIT_EXCEEDED",
    "START_FAILED",
    "ATTEMPTS_EXHAUSTED",
    "RERUN_REFUSED",
)

type Route = Literal["dispatch", "status"]
# An alias, not a bare annotation: a `type` value is evaluated only when asked for, so
# importing these contracts loads no HTTP library.
type HarnessTransport = httpx.AsyncBaseTransport
type JsonReader = Callable[[str], JsonValue]
type JsonWriter = Callable[[JsonValue], str]


@dataclass(frozen=True)
class OpenHarness:
    """Where the harness server listens (http://127.0.0.1:8081 in the image) and how long one
    call may take. Loaded by the application owner and passed explicitly."""

    base_url: str
    timeout_seconds: float


@dataclass(frozen=True)
class HarnessAnswer:
    """The harness's status code, and the JSON object it answered with the expected code."""

    status_code: int
    body: dict[str, JsonValue] | None


class HarnessAgents:
    """The logic's AgentRuns, backed by the harness server. Holds no connection: each call
    opens its own client, so there is no lifetime for the application to close."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float,
        read_json: JsonReader,
        write_json: JsonWriter,
        transport: HarnessTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout = timeout
        self.read_json = read_json
        self.write_json = write_json
        # None: the network. Tests pass an httpx.MockTransport standing for the harness; the
        # run (OpenHarness) never sets it.
        self.transport = transport

    async def submit(self, submission: Submission) -> RunId:
        if not TENANT.fullmatch(submission.tenant):
            raise AgentsUnavailableError("the tenant is not a harness path segment")
        payload: JsonValue = dict(submission.payload)
        # The harness encodes the argv string with ASCII escapes, so a non-ASCII character
        # counts its escaped bytes here too.
        if escaped_size(self.write_json(payload)) > MAX_INPUT_BYTES:
            raise SubmissionTooLargeError()
        body: JsonValue = {
            "agent_name": AGENTS[submission.work],
            "tenant_id": submission.tenant,
            "input": payload,
        }
        answer = await self.post("dispatch", body, expected=202)
        if answer.status_code == 413:
            raise SubmissionTooLargeError()  # the harness counted more than this side did
        if answer.body is None:
            raise AgentsUnavailableError(f"dispatch answered {answer.status_code}")
        process_id = answer.body.get("process_id")
        if not isinstance(process_id, str) or not PROCESS_ID.fullmatch(process_id):
            raise AgentsUnavailableError("dispatch answered without a process_id")
        return RunId(process_id)

    async def observe(self, tenant: str, run_id: str) -> Observation:
        if not TENANT.fullmatch(tenant) or not PROCESS_ID.fullmatch(run_id):
            return Observation(status=None, output=None)  # the harness could not know it
        asked: JsonValue = {"tenant_id": tenant, "process_id": run_id}
        answer = await self.post("status", asked, expected=200)
        if answer.status_code == 404:
            return Observation(status=None, output=None)
        if answer.body is None:
            raise AgentsUnavailableError(f"status answered {answer.status_code}")
        status, output = answer.body.get("status"), answer.body.get("output")
        reason = answer.body.get("reason")
        if not (output is None or isinstance(output, str)):
            raise AgentsUnavailableError("status answered an unexpected output")
        known = next((value for value in REASONS if value == reason), None)
        if reason is not None and known is None:
            raise AgentsUnavailableError("status answered an unknown reason")
        match status:
            case "queued" | "running" | "completed" | "failed":
                return Observation(status=status, output=output, reason=known)
            case _:
                raise AgentsUnavailableError("status answered an unknown status")

    async def post(self, route: Route, body: JsonValue, *, expected: int) -> HarnessAnswer:
        """One POST; the body is read (strict JSON, an object) only with the expected code."""
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url, timeout=self.timeout, transport=self.transport
            ) as client:
                response = await client.post(
                    f"/{route}",
                    content=self.write_json(body).encode("utf-8"),
                    headers={"content-type": "application/json"},
                )
        except httpx.HTTPError as error:
            raise AgentsUnavailableError(f"{route}: {type(error).__name__}") from error
        if response.status_code != expected:
            return HarnessAnswer(response.status_code, None)
        try:
            # The bytes are decoded strictly (response.text guesses and replaces); a
            # UnicodeDecodeError is a ValueError like any rejection of the decoder.
            value = self.read_json(response.content.decode("utf-8"))
        except ValueError:
            raise AgentsUnavailableError(f"{route} answered no JSON") from None
        if not isinstance(value, dict):
            raise AgentsUnavailableError(f"{route} answered no JSON object")
        return HarnessAnswer(response.status_code, value)
