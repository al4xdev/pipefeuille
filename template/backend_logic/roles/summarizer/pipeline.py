lazy from typing import Literal, Self

lazy from backend_logic._shared.json.decode import run as decoding
lazy from backend_logic._shared.json.decode.contracts import DecodeText

lazy from .container import Container
lazy from .contracts import (
    Language,
    Model,
    ModelRequest,
    NoteView,
    ProposedSummary,
    SummarizeNote,
    Summary,
    SummaryRejectedError,
)


class Pipe:
    def __init__(self) -> None:
        self.container = Container()

    @classmethod
    def get(cls, initial: SummarizeNote) -> Self:
        """Set input unchanged; nothing is projected or sent yet."""
        pipe = cls()
        pipe.container.input = initial
        return pipe

    def project_note(self) -> Self:
        """Require input; set view with title/body only. Privacy is applied here, before prompts."""
        if self.container.input is None:
            raise RuntimeError("note projection requires input")
        note = self.container.input.note
        self.container.view = NoteView(title=note.name, body=note.body)
        return self

    def prepare_prompt(self, *, language: Language) -> Self:
        """Require view; set system/user text from the view only. No I/O."""
        if self.container.view is None:
            raise RuntimeError("prompt preparation requires projected view")
        self.container.system = (
            f"Summarize the note in {language}. "
            'Reply with JSON: {"sentences": ["..."]}, at most three sentences.'
        )
        self.container.user = f"Title: {self.container.view.title}\n\n{self.container.view.body}"
        return self

    def prepare_request(
        self, *, output_tokens: int, response_mode: Literal["text", "structured"]
    ) -> Self:
        """Require system/user; set provider-neutral request. Budget is in tokens."""
        if self.container.system is None or self.container.user is None:
            raise RuntimeError("request preparation requires prompt text")
        self.container.request = ModelRequest(
            system=self.container.system,
            user=self.container.user,
            output_tokens=output_tokens,
            response_mode=response_mode,
        )
        return self

    async def call(self, *, model: Model) -> Self:
        """Require request; set reply. One logical model call (paid effect); never repeated here."""
        if self.container.request is None:
            raise RuntimeError("model call requires prepared request")
        if self.container.reply is not None:
            raise RuntimeError("model call was already attempted")
        self.container.reply = await model.complete(self.container.request)
        return self

    def decode_reply(self) -> Self:
        """Require reply; set proposal from strict JSON. Shape errors reject; no repair."""
        if self.container.reply is None:
            raise RuntimeError("reply decoding requires model reply")
        try:
            value = decoding.run(DecodeText(self.container.reply.content))
        except ValueError as error:
            raise SummaryRejectedError("reply is not strict JSON") from error
        if not isinstance(value, dict) or set(value) != {"sentences"}:
            raise SummaryRejectedError("reply must be an object with only 'sentences'")
        sentences = value["sentences"]
        if not isinstance(sentences, list):
            raise SummaryRejectedError("'sentences' must be a list")
        texts = tuple(item for item in sentences if isinstance(item, str))
        if len(texts) != len(sentences):
            raise SummaryRejectedError("every sentence must be text")
        self.container.proposal = ProposedSummary(sentences=texts)
        return self

    def admit_summary(self, *, max_sentences: int) -> Self:
        """Require proposal; set summary only if nonempty, nonblank and within the limit."""
        if self.container.proposal is None:
            raise RuntimeError("summary admission requires proposal")
        sentences = self.container.proposal.sentences
        if not sentences or len(sentences) > max_sentences:
            raise SummaryRejectedError("summary sentence count is outside the contract")
        if any(not sentence.strip() for sentence in sentences):
            raise SummaryRejectedError("summary sentences must not be blank")
        self.container.summary = Summary(sentences=tuple(s.strip() for s in sentences))
        return self

    def materialize(self) -> Summary:
        """Require admitted summary; the raw reply and proposal are not exposed."""
        if self.container.summary is None:
            raise RuntimeError("summarizer result requires admitted summary")
        return self.container.summary
