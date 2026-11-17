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

import random
import tomllib
from pathlib import Path

from architecture import (
    ROOT,
    binding_problems,
    build_graph,
    declaration_problems,
    render_json,
    render_text,
)
from declarations import (
    Content,
    Setting,
    lexical_problems,
    misplaced_declarations,
    parse_declaration,
    read_catalogues,
)

LOGIC = ROOT / "backend_logic"


def write_tree(root: Path, files: dict[str, str]) -> None:
    for relative, source in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")


def test_declaration_reader_is_strict() -> None:
    # Guards the guard: each rule of the closed subset fires on a source that breaks it.
    good = (
        "# comment\n\n"
        'use_case = "notes/list"\n'
        'summary = "Lists the notes."\n\n'
        "[settings]\n"
        'route = "/notes"\n'
        "max_bytes = 1_048_576\n"
        "offset = -3\n"
    )
    settings: dict[str, Setting] = {"route": "/notes", "max_bytes": 1048576, "offset": -3}
    assert parse_declaration(good) == (Content("notes/list", "Lists the notes.", settings), [])
    head_only = 'use_case = "notes/list"\r\nsummary = "x"\r\n'  # CRLF ends a line, as in TOML
    assert parse_declaration(head_only) == (Content("notes/list", "x"), [])
    # 1. Lexical: the line outside the subset, whatever the rest says.
    lexical = (
        "[other]\n"  # another table
        "[settings.deep]\n"  # a nested table
        "flag = true\n"  # a boolean
        "ratio = 0.5\n"  # a float
        'tags = ["a"]\n'  # an array
        "limit = 007\n"  # a leading zero
        'summary = "x" # trailing\n'  # an inline comment
        'summary="x"\n'  # the spacing
        'summary = "a \\" b"\n'  # an escape
        'a.b = "x"\n'  # a dotted key
        'use_case = "notes/list"\x0b\n'  # a vertical tab is no line end in TOML
        "# \x01\n"  # a control character in a comment
        'summary = "x"\r'  # a lone CR
    )
    assert parse_declaration(lexical) == (
        None,
        [
            f'line {number}: not `key = "text"` or `key = 123`: {line!r}'
            for number, line in enumerate(lexical.split("\n"), start=1)
            if line
        ],
    )
    # 2. TOML: a repeated key or header, which only the parse sees.
    assert parse_declaration('use_case = "a"\nuse_case = "b"\n') == (
        None,
        ["not TOML: Cannot overwrite a value (at line 2, column 15)"],
    )
    assert parse_declaration("[settings]\n[settings]\n") == (
        None,
        ["not TOML: Cannot declare ('settings',) twice (at line 2, column 10)"],
    )
    # 3. Structure: what each key is and where it sits.
    assert parse_declaration(
        'route = "/notes"\n'  # a project key in the head
        "use_case = 3\n"
        'summary = " "\n'
        "[settings]\n"
        'use_case = "notes/list"\n'  # a head key below the header
    ) == (
        None,
        [
            "unknown key 'route'; the head keys are ['use_case', 'summary'], and a project's "
            "own keys go under [settings]",
            "use_case: must be a string",
            "[settings] use_case: a head key; write it before [settings]",
            "summary: empty",
        ],
    )
    assert parse_declaration('use_case = "_shared/json/decode"\nsummary = "x"\n[settings]\n') == (
        None,
        [
            "[settings]: empty; leave the header out",
            "use_case: '_shared/json/decode' is not a package path under backend_logic "
            "(`notes/list`)",
        ],
    )
    assert parse_declaration("") == (None, ["missing key 'use_case'", "missing key 'summary'"])


PIECES = (
    *("a", "1", "_", "-", ".", "0", " ", "\t", '"', "\\", "#", "=", "[", "]", "é", "\x0b"),
    *("\x01", "\x7f", "\u2028", "\r", "true", "0.5", "settings", "use_case", "summary"),
)


def test_lexical_subset_never_accepts_what_tomllib_rejects() -> None:
    # The differential check: every line the lexical check lets through is a line tomllib
    # reads with the same value. A seeded sample of near-miss lines, so a failure reproduces.
    rng = random.Random(810)
    lines = ["[settings]", 'k = ""', "k = 0", "k = -1_000", "k = 1_0", '#  "x" \\']
    for _ in range(20000):
        key = "".join(rng.choice(PIECES) for _ in range(rng.randint(1, 2)))
        value = "".join(rng.choice(PIECES) for _ in range(rng.randint(0, 4)))
        quoted = rng.random() < 0.5
        lines.append(f'{key} = "{value}"' if quoted else f"{key} = {value}")
        lines.append("".join(rng.choice(PIECES) for _ in range(rng.randint(1, 5))))
    accepted = 0
    for line in lines:
        if lexical_problems(line):
            continue
        accepted += 1
        # Alone, after a head, and under the table (a header cannot repeat): each must parse.
        texts = [line, f'head = "x"\n{line}\n']
        if line != "[settings]":
            texts.append(f"[settings]\n{line}\r\n")
        for text in texts:
            tomllib.loads(text)
        key, separator, value = line.partition(" = ")
        if separator and not line.startswith("#"):  # a comment may hold " = "
            parsed = tomllib.loads(line)[key]
            assert parsed == (value[1:-1] if value.startswith('"') else int(value)), line
    assert accepted > 100  # the sample really exercises the accepted side


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
