lazy from backend_logic._shared.agents.contracts import AgentRuns

lazy from .contracts import ReadSummary, SummaryState
lazy from .pipeline import Pipe


async def run(initial: ReadSummary, *, agents: AgentRuns, tenant: str) -> SummaryState:
    """Read where a summary agent run stands and, once it completed, admit its answer.

    Effects:
        network: one status read on the agent-runs port.
    Repeat:
        safe: a later call may see a later status, never another effect.
    Loops:
        none
    Concurrency:
        free
    Raises:
        SummaryRunMissingError: the runtime knows no such run for this tenant.
        AgentAnswerRejectedError: the completed run's output breaks the summary contract.
        AgentsUnavailableError: the runtime did not answer, or answered something unexpected.
    """
    pipe = Pipe.get(initial)
    await pipe.observe(agents=agents, tenant=tenant, work="note_summary")
    if pipe.container.observation is not None and pipe.container.observation.status == "completed":
        (
            pipe
                .decode_answer()
                    .admit_summary(max_chars=600)
        )
    return pipe.materialize()
