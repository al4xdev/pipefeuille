lazy from dataclasses import dataclass

lazy from backend_logic.roles.summarizer.contracts import SummarizeNote, Summary

lazy from .contracts import Digest, DigestNotes


@dataclass
class Container:
    input: DigestNotes | None = None
    requests: tuple[SummarizeNote, ...] | None = None
    summaries: tuple[Summary, ...] | None = None
    digest: Digest | None = None
