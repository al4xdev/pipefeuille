lazy from .contracts import Model, SummarizeNote, Summary
lazy from .pipeline import Pipe


async def run(initial: SummarizeNote, *, model: Model) -> Summary:
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
