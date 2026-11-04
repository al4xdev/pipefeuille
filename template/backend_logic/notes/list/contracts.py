lazy from dataclasses import dataclass

lazy from ..name.contracts import NoteName


@dataclass(frozen=True)
class ListNotes:
    """List every stored note name. No client input: the directory is server-owned."""


@dataclass(frozen=True)
class NoteNames:
    """Sorted, admitted note names without the JSON suffix; no document contents."""

    names: tuple[NoteName, ...]
