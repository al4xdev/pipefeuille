"""A typed fake of the agent-runs port (backend_logic/_shared/agents): no agent, no network.

It records every submission, answers `queued` until the test finishes a run, and keeps each
run to its tenant, as the harness does. `answer_from_payload` derives a finalize-style answer
from what the run was handed, so a test sees the projection travel, not a constant.

A project helper (not one of the template's support files): it changes with the port.
"""

import json
from uuid import uuid4

from backend_logic._shared.agents.contracts import (
    Observation,
    RunId,
    RunReason,
    RunStatus,
    Submission,
)


class FakeAgentRuns:
    def __init__(self) -> None:
        self.submissions: list[Submission] = []
        self.observed: list[tuple[str, str]] = []
        self.runs: dict[str, tuple[str, Observation]] = {}

    async def submit(self, submission: Submission) -> RunId:
        self.submissions.append(submission)
        run_id = RunId(str(uuid4()))
        self.runs[run_id] = (submission.tenant, Observation(status="queued", output=None))
        return run_id

    async def observe(self, tenant: str, run_id: str) -> Observation:
        self.observed.append((tenant, run_id))
        owner, observation = self.runs.get(run_id, ("", Observation(status=None, output=None)))
        if owner != tenant:
            return Observation(status=None, output=None)
        return observation

    def finish(
        self,
        run_id: str,
        *,
        output: str | None,
        status: RunStatus = "completed",
        reason: RunReason | None = None,
    ) -> None:
        tenant, _ = self.runs[run_id]
        self.runs[run_id] = (tenant, Observation(status=status, output=output, reason=reason))

    def answer_from_payload(self, run_id: str) -> None:
        """Complete the run with `{"summary": "<name>: <first sentence of text>"}` + newline,
        as the summarizer agent's finalize_summary writes it."""
        index = list(self.runs).index(run_id)
        payload = self.submissions[index].payload
        name, text = payload["name"], payload["text"]
        assert isinstance(name, str) and isinstance(text, str)
        first = text.split(".")[0].strip()
        answer: dict[str, str] = {"summary": f"{name}: {first}."}
        self.finish(run_id, output=json.dumps(answer) + "\n")
