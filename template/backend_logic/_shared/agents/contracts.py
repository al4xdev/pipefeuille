"""The agent-runs port: what the logic trades with whatever runs its agents.

An agent run is work done outside this process, by a separate agent process (the runtime
layer, backend_harness/). The logic knows only that a run accepts a submission, answers with a
run id, and later reports a status and a text output for that id. It names the work
(AgentWork), never an agent: which agent does a work is the adapter's table
(harness/contracts.py, AGENTS). The output is a proposal: whoever reads it admits it.

A grouping with no run: the consumers (the use cases that submit and read, the adapter, the
HTTP edge that opens the adapter) import these types.
"""

lazy from collections.abc import Mapping
lazy from dataclasses import dataclass
lazy from typing import Literal, NewType, Protocol

lazy from backend_logic._shared.json.contracts import JsonValue

# One per kind of work an agent does; widened as works are added. A work names what is done,
# not who does it, so an agent can be replaced without touching the use cases.
type AgentWork = Literal["note_summary"]
type RunStatus = Literal["queued", "running", "completed", "failed"]
# Why a run failed for good, when the runtime knows it (the harness server's reasons).
type RunReason = Literal["LIMIT_EXCEEDED", "START_FAILED", "ATTEMPTS_EXHAUSTED", "RERUN_REFUSED"]
# The runtime's own id for one run; a received string becomes one only after the adapter
# checked its grammar.
RunId = NewType("RunId", str)


@dataclass(frozen=True)
class Submission:
    """One run to start: the work, the tenant whose workspace and visibility it belongs to, and
    the payload the agent gets as its first message (already projected: nothing private)."""

    work: AgentWork
    tenant: str
    payload: Mapping[str, JsonValue]


@dataclass(frozen=True)
class Observation:
    """The runtime's answer for one run. status None: the runtime does not know the run (or it
    is another tenant's, which looks the same). output: the agent's answer once it ended."""

    status: RunStatus | None
    output: str | None
    reason: RunReason | None = None


class AgentRunsError(Exception):
    """The runtime did not take or answer the request; nothing is known to have started."""


class AgentsUnavailableError(AgentRunsError):
    """Unreachable, or answering with an unexpected status or body; worth retrying later."""


class SubmissionTooLargeError(AgentRunsError):
    """The payload exceeds what the runtime can carry; retrying will not help."""


class AgentRuns(Protocol):
    """Start agent runs and read them back. The implementation owns its transport; it never
    retries a submission (a lost answer would start the work twice)."""

    async def submit(self, submission: Submission) -> RunId: ...

    async def observe(self, tenant: str, run_id: str) -> Observation: ...
