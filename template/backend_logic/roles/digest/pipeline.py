lazy from typing import Self

lazy from backend_logic.roles.summarizer.contracts import SummarizeNote, Summary

lazy from .container import Container
lazy from .contracts import Digest, DigestNotes, DigestRejectedError


class Pipe:
    def __init__(self) -> None:
        self.container = Container()

    @classmethod
    def get(cls, initial: DigestNotes) -> Self:
        """Set input unchanged; nothing is validated or sent yet."""
        pipe = cls()
        pipe.container.input = initial
        return pipe

    def validate_notes(self, *, max_notes: int) -> Self:
        """Require input; verify 1..max_notes notes with distinct names. Never drops or dedups:
        a duplicate would pay twice for the same note, so the request is rejected instead."""
        if self.container.input is None:
            raise RuntimeError("note validation requires input")
        notes = self.container.input.notes
        if not notes or len(notes) > max_notes:
            raise DigestRejectedError("digest note count is outside the contract")
        if len({note.name for note in notes}) != len(notes):
            raise DigestRejectedError("digest notes must have distinct names")
        return self

    def prepare_requests(self) -> Self:
        """Require input; set one summarizer request per note, in input order. No I/O."""
        if self.container.input is None:
            raise RuntimeError("request preparation requires input")
        language = self.container.input.language
        self.container.requests = tuple(
            SummarizeNote(note=note, language=language) for note in self.container.input.notes
        )
        return self

    def integrate_summaries(self, summaries: tuple[Summary, ...]) -> Self:
        """Require requests; set summaries after the parallel barrier. The caller passes them in
        request order, never completion order; a count mismatch is a composition bug."""
        if self.container.requests is None:
            raise RuntimeError("integration requires prepared requests")
        if len(summaries) != len(self.container.requests):
            raise RuntimeError("integration requires one summary per request")
        self.container.summaries = summaries
        return self

    def materialize(self) -> Digest:
        """Require summaries; return them as the digest."""
        if self.container.summaries is None:
            raise RuntimeError("digest result requires integrated summaries")
        return Digest(summaries=self.container.summaries)
