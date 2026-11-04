"""The use cases this family answers. Each type lives in the package that owns it:
NoteName in name/, NoteRecord in save/. Children never import this module, so it can
import theirs without a cycle."""

lazy from .list.contracts import ListNotes, NoteNames
lazy from .save.contracts import SavedNote, SaveNote

type NotesRequest = ListNotes | SaveNote
type NotesResponse = NoteNames | SavedNote
