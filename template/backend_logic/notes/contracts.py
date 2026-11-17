"""The use cases this family answers. Each type lives in the package that owns it:
NoteRecord in save/, Resources in prepare/, NoteName in backend_logic/_shared/note_name/.
Children never import this module, so it can import theirs without a cycle."""

lazy from .list.contracts import ListNotes, NoteNames
lazy from .prepare.contracts import PrepareResources, Resources
lazy from .save.contracts import SavedNote, SaveNote
lazy from .summarize.contracts import DispatchedSummary, DispatchSummary
lazy from .summary.contracts import ReadSummary, SummaryState

type NotesRequest = PrepareResources | ListNotes | SaveNote | DispatchSummary | ReadSummary
type NotesResponse = Resources | NoteNames | SavedNote | DispatchedSummary | SummaryState
