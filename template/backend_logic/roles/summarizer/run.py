lazy from .contracts import Model, SummarizeNote, Summary
lazy from .pipeline import Pipe


async def run(initial: SummarizeNote, *, model: Model) -> Summary:
    """Summarize one note through an explicitly supplied model port.

    The model sees a projection of the note (title and body), never its author or revision.

    Effects:
        model: one call to the model port; the reply is a proposal admitted locally.
    Repeat:
        accumulates: every call is another model call, and the reply may differ.
    Loops:
        none
    Concurrency:
        free
    Raises:
        SummaryRejectedError: the reply is not strict JSON or breaks the summary contract.
    """
    pipe = (
        Pipe
            .get(initial)
                .project_note()
                    .prepare_prompt(language=initial.language)
                        .prepare_request(output_tokens=256, response_mode="structured")
    )
    await pipe.call(model=model)
    return (
        pipe
            .decode_reply()
                .admit_summary(max_sentences=3)
                    .materialize()
    )
