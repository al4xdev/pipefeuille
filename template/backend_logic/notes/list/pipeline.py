"""Discover note names without opening their documents."""

lazy from typing import Self

lazy from backend_logic._shared.note_name import run as naming
lazy from backend_logic._shared.note_name.contracts import NoteValidationError
lazy from backend_logic.notes._shared.storage.contracts import FileStore
lazy from backend_logic.notes._shared.storage.scan import run as scanning
lazy from backend_logic.notes._shared.storage.scan.contracts import ScanDirectory

lazy from .container import Container
lazy from .contracts import ListNotes, NoteNames


class Pipe:
    def __init__(self) -> None:
        self.container = Container()

    @classmethod
    def get(cls, initial: ListNotes) -> Self:
        """Set input unchanged; the directory is chosen by run, not by the caller."""
        pipe = cls()
        pipe.container.input = initial
        return pipe

    def scan_directory(self, *, store: FileStore, relative: str) -> Self:
        """Set files directly beneath relative through storage. Read-only I/O.

        Confinement belongs to storage/path; a directory never written yet is ().
        """
        self.container.files = scanning.run(ScanDirectory(store, relative))
        return self

    def select_stems(self, *, suffix: str) -> Self:
        """Require files; set stems of those with the suffix, without reading them."""
        files = self.container.files
        if files is None:
            raise RuntimeError("note files are required")
        self.container.stems = tuple(
            file.removesuffix(suffix) for file in files if file.endswith(suffix)
        )
        return self

    def admit_names(self) -> Self:
        """Require stems; set names admitted by the shared note_name authority. No I/O.

        A stem it rejects fails the listing (ValueError): a misnamed file is corruption
        to report, not something to hide by filtering.
        """
        stems = self.container.stems
        if stems is None:
            raise RuntimeError("note stems are required")
        try:
            self.container.names = tuple(naming.run(stem) for stem in stems)
        except NoteValidationError as error:
            raise ValueError("stored note file name is invalid") from error
        return self

    def sort_names(self) -> Self:
        """Require names; replace names with their sorted order. No I/O."""
        names = self.container.names
        if names is None:
            raise RuntimeError("note names are required")
        self.container.names = tuple(sorted(names))
        return self

    def materialize(self) -> NoteNames:
        """Require completed names, including a legitimately empty tuple; return NoteNames."""
        names = self.container.names
        if names is None:
            raise RuntimeError("note names are required")
        return NoteNames(names=names)
