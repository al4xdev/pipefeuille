"""The use cases this family answers. Each type lives in the package that owns it."""

lazy from .digest.contracts import Digest, DigestNotes
lazy from .summarizer.contracts import SummarizeNote, Summary

type RolesRequest = SummarizeNote | DigestNotes
type RolesResponse = Summary | Digest
