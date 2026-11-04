lazy from typing import Self

lazy from .._shared.path import run as locating
lazy from .._shared.path.contracts import ResolvePath
lazy from .container import Container
lazy from .contracts import ScanDirectory


class Pipe:
    def __init__(self) -> None:
        self.container = Container()

    @classmethod
    def get(cls, initial: ScanDirectory) -> Self:
        """Set input unchanged; nothing is listed yet."""
        pipe = cls()
        pipe.container.input = initial
        return pipe

    def resolve_directory(self) -> Self:
        """Require input; set directory confined by the shared path sibling. No I/O."""
        if self.container.input is None:
            raise RuntimeError("directory scan requires input")
        initial = self.container.input
        self.container.directory = locating.run(ResolvePath(initial.store, initial.relative))
        return self

    def read_entries(self) -> Self:
        """Require directory; set immediate entries. A missing directory is observed as ().

        Every other I/O error propagates. Nothing is created: reading has no side effects.
        """
        if self.container.directory is None:
            raise RuntimeError("directory scan requires resolved directory")
        try:
            self.container.entries = tuple(self.container.directory.iterdir())
        except FileNotFoundError:
            self.container.entries = ()
        return self

    def select_files(self) -> Self:
        """Require entries; set names of regular files only, without opening them."""
        if self.container.entries is None:
            raise RuntimeError("file selection requires entries")
        self.container.files = tuple(
            entry.name for entry in self.container.entries if entry.is_file()
        )
        return self

    def materialize(self) -> tuple[str, ...]:
        """Require files, including a legitimately empty tuple; return them unsorted."""
        if self.container.files is None:
            raise RuntimeError("scanned files are required")
        return self.container.files
