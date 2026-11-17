lazy from typing import Self

lazy from backend_logic._shared.agents.contracts import AgentRuns, AgentWork
lazy from backend_logic._shared.json.decode import run as decoding
lazy from backend_logic._shared.json.decode.contracts import DecodeText

lazy from .container import Container
lazy from .contracts import (
    AgentAnswerRejectedError,
    NoteSummary,
    ReadSummary,
    SummaryRunMissingError,
    SummaryState,
)


class Pipe:
    def __init__(self) -> None:
        self.container = Container()

    @classmethod
    def get(cls, initial: ReadSummary) -> Self:
        """Set input unchanged; nothing is asked yet."""
        pipe = cls()
        pipe.container.input = initial
        return pipe

    async def observe(self, *, agents: AgentRuns, tenant: str, work: AgentWork) -> Self:
        """Require input; set observation of the run, which must be one of that work's (the
        answer admitted below is that work's contract). One status read, safe to repeat.

        A run the runtime does not know is SummaryRunMissingError.
        """
        if self.container.input is None:
            raise RuntimeError(f"reading a {work} run requires input")
        observation = await agents.observe(tenant, self.container.input.run_id)
        if observation.status is None:
            raise SummaryRunMissingError("summary_run_missing")
        self.container.observation = observation
        return self

    def decode_answer(self) -> Self:
        """Require a completed observation; set answer from its output as strict JSON.

        A completed run without output, or output that is no JSON, is AgentAnswerRejectedError.
        """
        observation = self.container.observation
        if observation is None or observation.status != "completed":
            raise RuntimeError("decoding the answer requires a completed run")
        if observation.output is None:
            raise AgentAnswerRejectedError("the completed run has no output")
        try:
            self.container.answer = decoding.run(DecodeText(observation.output))
        except ValueError as error:
            raise AgentAnswerRejectedError("the output is not strict JSON") from error
        return self

    def admit_summary(self, *, max_chars: int) -> Self:
        """Require answer; set summary only for {"summary": <nonblank text within max_chars>}.

        The agent's own tool checks the same rule; it is checked again here because the output
        is a proposal, whatever produced it.
        """
        answer = self.container.answer
        if not isinstance(answer, dict) or set(answer) != {"summary"}:
            raise AgentAnswerRejectedError("the answer must be an object with only 'summary'")
        text = answer["summary"]
        if not isinstance(text, str) or not text.strip():
            raise AgentAnswerRejectedError("the summary must be nonblank text")
        if len(text.strip()) > max_chars:
            raise AgentAnswerRejectedError("the summary is longer than the contract allows")
        self.container.summary = NoteSummary(text=text.strip())
        return self

    def materialize(self) -> SummaryState:
        """Require observation (and summary when completed); the raw output is not exposed."""
        observation = self.container.observation
        if observation is None or observation.status is None:
            raise RuntimeError("summary state requires an observation")
        if observation.status == "completed" and self.container.summary is None:
            raise RuntimeError("a completed run requires its admitted summary")
        return SummaryState(
            status=observation.status, summary=self.container.summary, reason=observation.reason
        )
