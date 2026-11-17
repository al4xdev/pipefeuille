"""Read the declaration catalogues of backend_logic: `<package>/apps/<name>/app.toml`.

A package whose mechanism use cases are bound to may hold a catalogue, `apps/`, with one
folder per app. Each app folder holds exactly one declaration, `app.toml`, and nothing else
(no Python, no other file, no folder); the declaration names the use case the app binds. A
declaration is data, never code (template-decisions A6):

- tests/gates/test_style.py knows the two folder kinds, `apps` and `app`, and their shape;
- tests/support/architecture.py makes no node of them: each app hangs on the package that
  holds the catalogue, and `binding_problems` holds its `use_case` to the graph;
- tests/gates/test_declarations.py reads every declaration with this reader and fails on a
  malformed one, a misplaced one or a broken binding.

The format is a closed subset of TOML:

    # a comment line; blank lines are allowed
    use_case = "notes/list"
    summary = "One line that says what the app is."

    [settings]
    route = "/notes"
    max_bytes = 1_048_576

The head has exactly HEAD, each once, both strings: the template's gates read them and hold
them to the code. `[settings]` is optional and holds the project's own keys: the gates check
only their form, never their meaning, so each one is held to the code by a project-owned test
in `tests/<family>/` (guide §2, "Declarations").

Reading is two checks, and a file passes only if it passes both:

1. `lexical_problems`, line by line: a blank line, a comment line, the header `[settings]`, or
   `key = value` with a lowercase key, exactly one space on each side of `=`, and a value that
   is a basic string without `"` or `\\`, or a decimal integer of at most 18 digits (`1_000`,
   `-3`; not `-0`). No line holds an invisible or control character (Unicode categories in
   HIDDEN). Anything else fails: another table, a dotted or quoted key, a float, a boolean,
   an array, an inline table, an inline comment.
2. `tomllib.loads` (typed by tests/support/tomllib.pyi, values `object`): it rejects a repeated
   key or a repeated header and gives the values their TOML meaning; which keys sit at the
   head and which under `[settings]` is then read from its result.

Never edited in a project, like the gates that use it: a new head key, a new table or a new
file name is a change to the pipefeuille (RUNBOOK, task C).
"""

import re
import tomllib
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

CATALOGUE = "apps"  # reserved folder name: a catalogue, never a package
DECLARATION = "app.toml"  # the one file an app folder holds
HEAD = ("use_case", "summary")  # the template's keys: read and held by its gates
SETTINGS = "settings"  # the one table: the project's keys, held by the project's tests

type Setting = str | int

KEY = re.compile(r"[a-z][a-z0-9_]*")
# An app folder's name, like a package's: it is read as a word, never quoted.
APP_NAME = re.compile(r"[a-z][a-z0-9_]*")
# Characters a reader cannot see or that change how a line displays: controls (C0 and C1, tab
# included), format characters (bidi overrides, zero-width spaces, a BOM), line and paragraph
# separators, private use and surrogates. Refused anywhere in a declaration.
HIDDEN = frozenset({"Cc", "Cf", "Zl", "Zp", "Co", "Cs"})
# A basic string with nothing that needs an escape: what is read is what TOML reads.
STRING = re.compile(r'"[^"\\\x00-\x1f\x7f]*"')
# A decimal TOML integer: no `+`, no leading zero, no `-0`, `_` only between digits, and at
# most 18 digits (tomllib refuses an int of more than 4300 digits with a bare ValueError).
INTEGER = re.compile(r"0|-?[1-9](_?[0-9]){0,17}")
# A comment without control characters (TOML forbids them there too).
COMMENT = re.compile(r"#[^\x00-\x1f\x7f]*")
# A package path under backend_logic: `notes/list`. `_shared` cannot match: a use case is
# never a shared package.
PACKAGE_PATH = re.compile(r"[a-z][a-z0-9_]*(/[a-z][a-z0-9_]*)*")


@dataclass(frozen=True)
class Content:
    """What one declaration says, after both checks."""

    use_case: str
    summary: str
    settings: dict[str, Setting] = field(default_factory=dict)


@dataclass(frozen=True)
class Declaration:
    path: str  # from the project root: backend_logic/notes/apps/list_notes/app.toml
    holder: str  # the package that holds the catalogue: backend_logic/notes
    name: str  # the app, its folder's name: list_notes
    use_case: str  # the bound use case, under backend_logic: notes/list
    summary: str
    settings: dict[str, Setting] = field(default_factory=dict)  # the project's keys


def lexical_problems(text: str) -> list[str]:
    """The lines outside the closed subset. A file with none is valid TOML or repeats a key."""
    problems: list[str] = []
    # Only LF or CRLF end a line, as in TOML: str.splitlines() would also split on \x0b, \x0c
    # or U+2028. A lone CR stays in its line and fails.
    for number, line in enumerate(text.replace("\r\n", "\n").split("\n"), start=1):
        hidden = sorted({f"U+{ord(c):04X}" for c in line if unicodedata.category(c) in HIDDEN})
        if hidden:
            problems.append(f"line {number}: invisible or control characters {hidden}")
            continue
        if not line.strip(" ") or COMMENT.fullmatch(line) or line == f"[{SETTINGS}]":
            continue
        key, separator, value = line.partition(" = ")
        if not (
            separator
            and KEY.fullmatch(key)
            and (STRING.fullmatch(value) or INTEGER.fullmatch(value))
        ):
            shown = line if len(line) <= 80 else line[:77] + "..."  # a 5000-digit value
            problems.append(f'line {number}: not `key = "text"` or `key = 123`: {shown!r}')
    return problems


def table(value: object) -> dict[str, object]:
    """A TOML table with its keys as str. isinstance alone would narrow to dict[Any, Any]."""
    if not isinstance(value, dict):
        raise TypeError("expected a TOML table")
    return {str(key): item for key, item in value.items()}


def structure(document: dict[str, object]) -> tuple[Content | None, list[str]]:
    """The head and `[settings]`, read from tomllib's result."""
    problems = [
        f"unknown key {key!r}; the head keys are {list(HEAD)}, and a project's own keys go "
        f"under [{SETTINGS}]"
        for key in document
        if key not in (*HEAD, SETTINGS)
    ]
    head: dict[str, str] = {}
    for key in HEAD:
        value = document.get(key)
        if value is None:
            problems.append(f"missing key {key!r}")
        elif not isinstance(value, str):
            problems.append(f"{key}: must be a string")
        else:
            head[key] = value
    settings: dict[str, Setting] = {}
    if SETTINGS in document:
        given = table(document[SETTINGS])
        if not given:
            problems.append(f"[{SETTINGS}]: empty; leave the header out")
        for key, value in given.items():
            if key in HEAD:
                problems.append(f"[{SETTINGS}] {key}: a head key; write it before [{SETTINGS}]")
            elif isinstance(value, str | int) and not isinstance(value, bool):
                settings[key] = value
            else:  # the lexical check already refuses it; the type is never assumed
                problems.append(f"[{SETTINGS}] {key}: must be a string or an integer")
    use_case = head.get("use_case")
    if use_case is not None and not PACKAGE_PATH.fullmatch(use_case):
        problems.append(
            f"use_case: {use_case!r} is not a package path under backend_logic (`notes/list`)"
        )
    summary = head.get("summary")
    if summary is not None and not summary.strip():
        problems.append("summary: empty")
    if problems or use_case is None or summary is None:
        return None, problems
    return Content(use_case, summary, settings), []


def parse_declaration(text: str) -> tuple[Content | None, list[str]]:
    """What one declaration says, or None and the problems of the first check that failed."""
    lexical = lexical_problems(text)
    if lexical:
        return None, lexical
    try:
        document = tomllib.loads(text)
    except ValueError as error:  # TOMLDecodeError: a repeated key or header
        return None, [f"not TOML: {error}"]
    return structure(document)


def declaration_files(logic: Path) -> list[Path]:
    """Every entry named like a declaration under logic, wherever it sits and whatever it is
    (a file, a folder, a symlink, a FIFO): a name is enough to be held to the rule."""
    return sorted(logic.rglob(DECLARATION))


def in_place(path: Path, logic: Path) -> bool:
    """`<holder>/apps/<name>/app.toml` under logic, with one catalogue on the path and no
    bytecode cache: the only place a declaration may sit. A catalogue inside an app, or a
    declaration in a cache, would hang on a holder that is data, not a package."""
    parts = path.relative_to(logic).parts
    return (
        len(parts) >= 3
        and parts[-3] == CATALOGUE
        and parts.count(CATALOGUE) == 1
        and "__pycache__" not in parts
    )


def misplaced_declarations(logic: Path) -> list[str]:
    """Declarations outside a catalogue's app folder: nothing reads them, the gate cannot
    hold them to the code, and a reader would not know which package they configure."""
    return [
        f"{path.relative_to(logic.parent).as_posix()}: a declaration sits only in "
        f"<package>/{CATALOGUE}/<name>/{DECLARATION}"
        for path in declaration_files(logic)
        if not in_place(path, logic)
    ]


def read_catalogues(logic: Path) -> tuple[list[Declaration], list[str]]:
    """Every well-formed declaration in place, in path order, and the problems of the rest."""
    found: list[Declaration] = []
    problems: list[str] = []
    for path in declaration_files(logic):
        if not in_place(path, logic):
            continue  # misplaced_declarations reports it
        relative = path.relative_to(logic.parent).as_posix()
        if path.is_symlink() or not path.is_file():  # reading a FIFO would block
            problems.append(f"{relative}: not a regular file")
            continue
        # Bytes, not read_text: universal newlines would turn a lone CR into a line end.
        try:
            text = path.read_bytes().decode("utf-8")
        except UnicodeDecodeError as error:
            problems.append(f"{relative}: not UTF-8: {error}")
            continue
        content, own = parse_declaration(text)
        problems.extend(f"{relative}: {problem}" for problem in own)
        if content is None:
            continue
        found.append(
            Declaration(
                path=relative,
                holder=path.parent.parent.parent.relative_to(logic.parent).as_posix(),
                name=path.parent.name,
                use_case=content.use_case,
                summary=content.summary,
                settings=content.settings,
            )
        )
    return found, problems
