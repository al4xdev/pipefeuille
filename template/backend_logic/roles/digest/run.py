lazy import asyncio

lazy from backend_logic.roles.summarizer import run as summarizing
lazy from backend_logic.roles.summarizer.contracts import Model

lazy from .contracts import Digest, DigestNotes
lazy from .pipeline import Pipe


async def run(initial: DigestNotes, *, model: Model) -> Digest:
    """Summarize several notes at once: one summarizer run per note, in parallel.

    Effects:
        model: one summarizer call per note, at most eight.
    Repeat:
        accumulates: every call repeats all model calls.
    Loops:
        over-items: one summarizer task per validated note.
    Concurrency:
        free
    Raises:
        DigestRejectedError: no notes, more than eight, or repeated names; no model call made.
        ExceptionGroup: wraps the first SummaryRejectedError; the other calls are cancelled.
    """
    pipe = (
        Pipe
            .get(initial)
                .validate_notes(max_notes=8)
                    .prepare_requests()
    )
    if pipe.container.requests is None:
        raise RuntimeError("digest requires prepared requests before the parallel calls")
    # Failure policy: TaskGroup. The first rejected summary cancels the calls still running
    # and the whole digest fails as an ExceptionGroup; a partial digest is never returned.
    async with asyncio.TaskGroup() as group:
        tasks = [
            group.create_task(summarizing.run(request, model=model))
            for request in pipe.container.requests
        ]
    # After the barrier, in request order: the digest never depends on which call finished first.
    return (
        pipe
            .integrate_summaries(tuple(task.result() for task in tasks))
                .materialize()
    )
