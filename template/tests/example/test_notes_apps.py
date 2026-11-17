"""The notes family's catalogue: the apps there are, each bound to the package that serves it.

tests/gates/test_declarations.py holds the head of every declaration (`use_case`, `summary`)
to the code. The keys under `[settings]` are the project's: the template's gates know only
their form, so this file holds each one to the code (guide §2, "Declarations"). It also pins
the catalogue, so a new app of notes, or a new key, changes it on purpose. It goes away with
notes/.
"""

from pathlib import Path

from declarations import Declaration, read_catalogues
from wire_client import serving

from backend_logic.notes.list.contracts import ListNotes
from http_adapter.application import create_app

ROOT = Path(__file__).resolve().parents[2]


def list_notes() -> Declaration:
    declarations, problems = read_catalogues(ROOT / "backend_logic")
    assert not problems
    (app,) = declarations
    return app


def test_the_notes_catalogue_is_the_apps_there_are() -> None:
    assert list_notes() == Declaration(
        path="backend_logic/notes/apps/list_notes/app.toml",
        holder="backend_logic/notes",
        name="list_notes",
        use_case="notes/list",
        summary="Exposes the sorted names of the stored notes; reads only.",
        settings={"route": "/notes"},
    )


def test_the_bound_use_case_is_the_package_that_defines_its_request() -> None:
    # The declaration names the package a reader opens to see what the app runs: the one that
    # defines the request the notes family dispatches to it.
    module = "backend_logic." + list_notes().use_case.replace("/", ".") + ".contracts"
    assert ListNotes.__module__ == module


async def test_the_declared_route_serves_the_bound_use_case(tmp_path: Path) -> None:
    # The project key `route`: a GET on it answers with what notes/list materializes (the
    # sorted names), so the declaration and the HTTP adapter cannot drift apart.
    route = list_notes().settings["route"]
    assert isinstance(route, str)
    async with serving(create_app(data_root=tmp_path / "data")) as client:
        for name in ("b", "a"):
            created = await client.put(f"/notes/{name}", b'{"body": "x"}')
            assert created.status == 200
        listed = await client.get(route)
    assert (listed.status, listed.body) == (200, {"names": ["a", "b"]})
