"""The notes family's catalogue: the apps there are, each bound to the package that serves it.

tests/gates/test_declarations.py holds every declaration to the code; this file pins the
example's catalogue, so a new app of notes changes it on purpose. It goes away with notes/.
"""

from pathlib import Path

from declarations import Declaration, read_catalogues

from backend_logic.notes.list.contracts import ListNotes

ROOT = Path(__file__).resolve().parents[2]


def test_the_notes_catalogue_is_the_apps_there_are() -> None:
    declarations, problems = read_catalogues(ROOT / "backend_logic")
    assert not problems
    assert declarations == [
        Declaration(
            path="backend_logic/notes/apps/list_notes/app.toml",
            holder="backend_logic/notes",
            name="list_notes",
            use_case="notes/list",
            summary="Exposes the sorted names of the stored notes; reads only.",
        )
    ]


def test_the_bound_use_case_is_the_package_that_defines_its_request() -> None:
    # The declaration names the package a reader opens to see what the app runs: the one that
    # defines the request the notes family dispatches to it.
    (app,) = read_catalogues(ROOT / "backend_logic")[0]
    module = "backend_logic." + app.use_case.replace("/", ".") + ".contracts"
    assert ListNotes.__module__ == module
