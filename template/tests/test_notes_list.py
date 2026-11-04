"""Actual listing behavior plus package and segment composition rehearsals."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Self

import pytest

from backend_logic.notes.list.container import Container
from backend_logic.notes.list.contracts import ListNotes, NoteNames
from backend_logic.notes.list.pipeline import Pipe
from backend_logic.notes.list.run import run
from backend_logic.notes.name.contracts import NoteName
from backend_logic.storage.path.contracts import FileStore

type Call = (
    tuple[Literal["scan_directory", "select_stems"], str]
    | tuple[Literal["admit_names", "sort_names", "materialize"], None]
)


@dataclass
class RecordingContainer(Container):
    calls: list[Call] = field(default_factory=list)


class RecordingFake(Pipe):
    """Explicit typed test double; fields it sets stay coherent with each stage's contract."""

    def __init__(self) -> None:
        self.container: RecordingContainer = RecordingContainer()

    def scan_directory(self, *, store: FileStore, relative: str) -> Self:
        self.container.calls.append(("scan_directory", relative))
        self.container.files = ("example.json", "notes.txt")
        return self

    def select_stems(self, *, suffix: str) -> Self:
        self.container.calls.append(("select_stems", suffix))
        if self.container.files is None:
            raise RuntimeError("fixture requires files")
        self.container.stems = tuple(
            file.removesuffix(suffix) for file in self.container.files if file.endswith(suffix)
        )
        return self

    def admit_names(self) -> Self:
        self.container.calls.append(("admit_names", None))
        if self.container.stems is None:
            raise RuntimeError("fixture requires stems")
        # The fixture's stems are already valid; real admission is tested separately.
        self.container.names = tuple(NoteName(stem) for stem in self.container.stems)
        return self

    def sort_names(self) -> Self:
        self.container.calls.append(("sort_names", None))
        if self.container.names is None:
            raise RuntimeError("fixture requires names")
        self.container.names = tuple(sorted(self.container.names))
        return self

    def materialize(self) -> NoteNames:
        self.container.calls.append(("materialize", None))
        if self.container.names is None:
            raise RuntimeError("fixture requires names")
        return NoteNames(names=self.container.names)


def test_public_run_lists_real_temporary_entries(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    assert Pipe().container == Container()
    assert run(ListNotes(), store=store) == NoteNames(names=())
    # Listing is read-only: a directory never written is observed empty, not created.
    assert not (tmp_path / "notes").exists()
    directory = tmp_path / "notes"
    directory.mkdir()
    (directory / "zeta.json").write_text("not parsed by discovery", encoding="utf-8")
    (directory / "alpha.json").write_text("{}", encoding="utf-8")
    (directory / "ignored.txt").write_text("{}", encoding="utf-8")
    (directory / "folder.json").mkdir()
    assert run(ListNotes(), store=store) == NoteNames(names=(NoteName("alpha"), NoteName("zeta")))


def test_real_run_composes_the_declared_contract_with_a_fake(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    initial = ListNotes()
    fake = RecordingFake.get(initial)
    received: list[ListNotes] = []

    def factory(value: ListNotes) -> Pipe:
        received.append(value)
        return fake

    monkeypatch.setattr(Pipe, "get", staticmethod(factory))
    assert run(initial, store=FileStore(tmp_path)) == NoteNames(names=(NoteName("example"),))
    assert received == [initial]
    assert fake.container.calls == [
        ("scan_directory", "notes"),
        ("select_stems", ".json"),
        ("admit_names", None),
        ("sort_names", None),
        ("materialize", None),
    ]


def test_middle_segment_uses_an_explicit_post_scan_fixture() -> None:
    pipe = Pipe.get(ListNotes())
    pipe.container.files = ("b.json", "a.txt")

    assert pipe.select_stems(suffix=".json").admit_names().sort_names().materialize() == (
        NoteNames(names=(NoteName("b"),))
    )


def test_misnamed_file_fails_the_listing_instead_of_disappearing(tmp_path: Path) -> None:
    directory = tmp_path / "notes"
    directory.mkdir()
    (directory / "fine.json").write_text("{}", encoding="utf-8")
    (directory / "bad name.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="stored note file name is invalid"):
        run(ListNotes(), store=FileStore(tmp_path))
