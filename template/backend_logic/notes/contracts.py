"""The use cases this family answers. Each type lives in the package that owns it:
NoteRecord in save/, Resources in prepare/, NoteName in backend_logic/_shared/note_name/.
Children never import this module, so it can import theirs without a cycle."""

lazy from .list.contracts import ListNotes, NoteNames
lazy from .prepare.contracts import PrepareResources, Resources
lazy from .save.contracts import SavedNote, SaveNote

type NotesRequest = PrepareResources | ListNotes | SaveNote
type NotesResponse = Resources | NoteNames | SavedNote
