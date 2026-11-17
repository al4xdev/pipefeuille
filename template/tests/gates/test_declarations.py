"""Hold every declaration (`<package>/apps/<name>/app.toml`) to the code it binds.

A declaration is data that names a use case (template-decisions A6, guide §2 "Declarations").
A value the code does not hold would bind a door to nothing, so each one must be:

- in place: no `app.toml` outside a catalogue's app folder (the shape of the folders is
  tests/gates/test_style.py's; this file looks at the files);
- well formed: read by tests/support/declarations.py, a closed TOML subset (unknown, repeated
  or missing keys fail);
- bound: its `use_case` is a package with a `run.py` that a family dispatches by `case`, and
  it sits in the package that holds the catalogue or calls it (tests/support/architecture.py,
  `binding_problems`).

A declaration that a real package needs to break this is a proposal to the owner (AGENTS.md,
"Deviations"), never a reason to edit this file.
"""

from pathlib import Path

from architecture import (
    ROOT,
    binding_problems,
    build_graph,
    declaration_problems,
    render_json,
    render_text,
)
from declarations import misplaced_declarations, parse_declaration, read_catalogues

LOGIC = ROOT / "backend_logic"


def write_tree(root: Path, files: dict[str, str]) -> None:
    for relative, source in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")


def test_declaration_reader_is_strict() -> None:
    # Guards the guard: each rule of the closed schema fires on a source that breaks it.
    good = '# comment\n\nuse_case = "notes/list"\nsummary = "Lists the notes."\n'
    assert parse_declaration(good) == (
        {"use_case": "notes/list", "summary": "Lists the notes."},
        [],
    )
    bad = (
        'use_case = "notes/list"\n'
        'use_case = "notes/save"\n'  # repeated
        'route = "/notes"\n'  # unknown key
        "[settings]\n"  # a table
        "limit = 3\n"  # not a string
        'summary = "x" # trailing\n'  # inline comment
        'summary="x"\n'  # spacing
        'summary = "a \\" b"\n'  # an escape
    )
    assert parse_declaration(bad) == (
        {},
        [
            "line 2: repeated key 'use_case'",
            "line 3: unknown key 'route'; the keys are ['use_case', 'summary']",
            "line 4: not `key = \"value\"`: '[settings]'",
            "line 5: not `key = \"value\"`: 'limit = 3'",
            'line 6: not `key = "value"`: \'summary = "x" # trailing\'',
            'line 7: not `key = "value"`: \'summary="x"\'',
            'line 8: not `key = "value"`: \'summary = "a \\\\" b"\'',
            "missing key 'summary'",
        ],
    )
    assert parse_declaration('use_case = "_shared/json/decode"\nsummary = " "\n') == (
        {},
        [
            "use_case: '_shared/json/decode' is not a package path under backend_logic "
            "(`notes/list`)",
            "summary: empty",
        ],
    )
    assert parse_declaration("") == ({}, ["missing key 'use_case'", "missing key 'summary'"])
    # Only LF and CRLF end a line, as in TOML; a vertical tab or a control character in a
    # comment would pass str.splitlines() and fail tomllib.
    crlf = 'use_case = "notes/list"\r\nsummary = "x"\r\n'
    assert parse_declaration(crlf) == ({"use_case": "notes/list", "summary": "x"}, [])
    assert parse_declaration('use_case = "notes/list"\x0b\n# \x01\nsummary = "x"\r') == (
        {},
        [
            'line 1: not `key = "value"`: \'use_case = "notes/list"\\x0b\'',
            "line 2: not `key = \"value\"`: '# \\x01'",
            'line 3: not `key = "value"`: \'summary = "x"\\r\'',
            "missing key 'use_case'",
            "missing key 'summary'",
        ],
    )


def run_source() -> str:
    return "def run(initial):\n    pass\n"


def app(use_case: str) -> str:
    return f'use_case = "{use_case}"\nsummary = "An app."\n'


SYNTHETIC = {
    "backend_logic/contracts.py": "type BackendRequest = A | B\n",
    "backend_logic/run.py": (
        "lazy from .a import run as a_run\n"
        "lazy from .b import run as b_run\n\n\n"
        "def run(initial):\n"
        "    match initial:\n"
        "        case A():\n"
        "            a_run.run(initial)\n"
        "        case B():\n"
        "            b_run.run(initial)\n"
    ),
    "backend_logic/a/contracts.py": "class A: ...\n",
    "backend_logic/a/run.py": (
        "lazy from backend_logic.m import run as configuring\n"
        "lazy from .step import run as stepping\n\n\n"
        "def run(initial):\n"
        "    stepping.run(initial)\n"
        "    configuring.run(initial)\n"
    ),
    "backend_logic/a/step/run.py": run_source(),
    "backend_logic/b/contracts.py": "class B: ...\n",
    "backend_logic/b/run.py": run_source(),
    # m holds the catalogue; a calls m, b does not.
    "backend_logic/m/run.py": run_source(),
    "backend_logic/m/apps/good/app.toml": app("a"),
    "backend_logic/m/apps/missing/app.toml": app("nowhere"),
    "backend_logic/m/apps/step/app.toml": app("a/step"),
    "backend_logic/m/apps/unrelated/app.toml": app("b"),
    "backend_logic/m/apps/broken/app.toml": 'use_case = "a"\n',
    # Outside a catalogue's app folder: beside a run.py, and one level too deep.
    "backend_logic/a/app.toml": app("a"),
    "backend_logic/m/apps/good/extra/app.toml": app("a"),
}


def test_declaration_scanners_report_every_misplacement_and_broken_binding(
    tmp_path: Path,
) -> None:
    write_tree(tmp_path, SYNTHETIC)
    graph, _ = build_graph(tmp_path)
    assert declaration_problems(graph, tmp_path) == [
        "backend_logic/a/app.toml: a declaration sits only in <package>/apps/<name>/app.toml",
        "backend_logic/m/apps/good/extra/app.toml: a declaration sits only in "
        "<package>/apps/<name>/app.toml",
        "backend_logic/m/apps/broken/app.toml: missing key 'summary'",
        "backend_logic/m/apps/missing/app.toml: use_case 'nowhere' is not a package with a run.py",
        "backend_logic/m/apps/step/app.toml: use_case 'a/step' is not a use case "
        "(no family dispatches it by a case)",
        "backend_logic/m/apps/unrelated/app.toml: use_case 'b' neither sits in "
        "backend_logic/m nor calls it",
    ]
    # Declarations are data: no node below a catalogue; each app hangs on its holder.
    assert not [node_id for node_id in graph.nodes if "apps" in node_id.split(".")]
    holder = graph.nodes["backend_logic.m"]
    assert [declaration.name for declaration in holder.apps] == [
        "good",
        "missing",
        "step",
        "unrelated",
    ]
    text = render_text(graph)
    assert "  apps/good/  [app] binds a  An app." in text
    assert "│ bound by: m/apps/good" in text
    assert '"use_case": "a/step"' in render_json(graph)


def test_every_declaration_sits_in_a_catalogue() -> None:
    assert not misplaced_declarations(LOGIC)


def test_every_declaration_is_well_formed() -> None:
    _, problems = read_catalogues(LOGIC)
    assert not problems, "\n".join(problems)


def test_every_app_binds_a_use_case_of_its_holder() -> None:
    graph, _ = build_graph(ROOT)
    problems = binding_problems(graph, ROOT)
    assert not problems, "\n".join(problems)
