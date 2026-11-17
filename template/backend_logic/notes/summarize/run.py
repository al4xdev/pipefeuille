lazy from backend_logic._shared.agents.contracts import AgentRuns
lazy from backend_logic.notes._shared.storage.contracts import FileStore

lazy from .contracts import DispatchedSummary, DispatchSummary
lazy from .pipeline import Pipe


async def run(
    initial: DispatchSummary, *, store: FileStore, agents: AgentRuns, tenant: str
) -> DispatchedSummary:
    """Hand one stored note to the summary agent; notes/summary reads and admits its answer.

    The agent sees a projection of the note (name and text), never its author or revision.

    Effects:
        reads: the stored note.
        network: one submission to the agent-runs port (an agent process outside this one).
        model: the agent's run calls a language model; its cost is the run's.
    Repeat:
        accumulates: every call starts another agent run; nothing deduplicates them.
    Loops:
        none
    Concurrency:
        free: a note saved meanwhile is handed over as it was read.
    Raises:
        NoteValidationError: the name breaks the note-name grammar; nothing was read.
        NoteMissingError: no stored note has this name; nothing was handed over.
        SubmissionTooLargeError: the note is larger than an agent run can carry.
        AgentsUnavailableError: the runtime did not take the run; nothing is known to run.
        ValueError: the stored note is corrupt or misfiled.
    """
    pipe = (
        Pipe
            .get(initial)
                .validate_name()
                    .resolve_path(directory="notes", suffix=".json")
                        .read_note(store=store)
                            .project_note()
                                .prepare_submission(work="note_summary", tenant=tenant)
    )
    await pipe.submit(agents=agents, work="note_summary")
    return pipe.materialize()
