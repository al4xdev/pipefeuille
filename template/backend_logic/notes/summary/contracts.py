lazy from dataclasses import dataclass

lazy from backend_logic._shared.agents.contracts import RunReason, RunStatus


@dataclass(frozen=True)
class ReadSummary:
    """Where the agent run of one DispatchSummary stands; run_id as it answered it."""

    run_id: str


@dataclass(frozen=True)
class NoteSummary:
    """Admitted summary: nonblank plain text within the declared size."""

    text: str


@dataclass(frozen=True)
class SummaryState:
    """status as the runtime reports it; summary only once completed and admitted; reason only
    for a run that failed for a reason the runtime knows."""

    status: RunStatus
    summary: NoteSummary | None
    reason: RunReason | None


class SummaryRunMissingError(LookupError):
    """The runtime knows no run with this id for this tenant (another tenant's looks the same)."""


class AgentAnswerRejectedError(ValueError):
    """The agent's output broke the summary contract; nothing is admitted and nothing retried."""
