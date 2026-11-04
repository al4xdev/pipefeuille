lazy from pathlib import Path
lazy from typing import Self

lazy from .container import Container
lazy from .contracts import ResolvePath


class Pipe:
    def __init__(self) -> None:
        self.container = Container()

    @classmethod
    def get(cls, initial: ResolvePath) -> Self:
        """Set input unchanged; nothing is joined yet."""
        pipe = cls()
        pipe.container.input = initial
        return pipe

    def validate_segments(self) -> Self:
        """Require input; set segments only if every raw segment is a plain name.

        Raw segments are checked because PurePosixPath silently drops "" and ".".
        Lexical confinement only; symlink-hostile filesystems are out of scope.
        Raise ValueError; no I/O, no correction.
        """
        if self.container.input is None:
            raise RuntimeError("path resolution requires input")
        relative = self.container.input.relative
        segments = tuple(relative.split("/"))
        if any(segment in ("", ".", "..") for segment in segments) or any(
            character in relative for character in ("\\", "\x00")
        ):
            raise ValueError("storage paths must stay beneath the store root")
        self.container.segments = segments
        return self

    def join_root(self) -> Self:
        """Require input and validated segments; set the absolute path. No I/O."""
        if self.container.input is None or self.container.segments is None:
            raise RuntimeError("path join requires validated segments")
        self.container.path = self.container.input.store.root.joinpath(*self.container.segments)
        return self

    def materialize(self) -> Path:
        """Require path; return it."""
        if self.container.path is None:
            raise RuntimeError("resolved path is required")
        return self.container.path
