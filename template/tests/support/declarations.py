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

The format is a closed subset of TOML, read with the standard library only, so every file
this reader accepts is valid TOML with the same meaning:

    # a comment line; blank lines are allowed
    use_case = "notes/list"
    summary = "One line that says what the app is."

One `key = "value"` per line, with exactly one space on each side of `=`. The keys are KEYS,
each exactly once. A value is a basic string without `"`, `\\` or control characters. Anything
else fails: another key, a repeated key, a table, a number, a boolean, an inline comment.

Never edited in a project, like the gates that use it: a new key or a new file name is a
change to the pipefeuille (RUNBOOK, task C).
"""

import re
from dataclasses import dataclass
from pathlib import Path

CATALOGUE = "apps"  # reserved folder name: a catalogue, never a package
DECLARATION = "app.toml"  # the one file an app folder holds
KEYS = ("use_case", "summary")
# Broad on purpose (TOML bare keys), so a key outside KEYS is reported as unknown, not malformed.
BARE_KEY = re.compile(r"[A-Za-z0-9_-]+")
# A basic string with nothing that needs an escape: what is read is what TOML reads.
PLAIN_VALUE = re.compile(r'"[^"\\\x00-\x1f\x7f]*"')
# A comment without control characters (TOML forbids them there too).
COMMENT = re.compile(r"#[^\x00-\x1f\x7f]*")
# A package path under backend_logic: `notes/list`. `_shared` cannot match: a use case is
# never a shared package.
PACKAGE_PATH = re.compile(r"[a-z][a-z0-9_]*(/[a-z][a-z0-9_]*)*")


@dataclass(frozen=True)
class Declaration:
    path: str  # from the project root: backend_logic/notes/apps/list_notes/app.toml
    holder: str  # the package that holds the catalogue: backend_logic/notes
    name: str  # the app, its folder's name: list_notes
    use_case: str  # the bound use case, under backend_logic: notes/list
    summary: str


def parse_declaration(text: str) -> tuple[dict[str, str], list[str]]:
    """The keys of one declaration and every problem in it; values only when there is none."""
    values: dict[str, str] = {}
    problems: list[str] = []
    # Only LF or CRLF end a line, as in TOML: str.splitlines() would also split on \x0b, \x0c
    # or U+2028 and accept a file that TOML rejects. A lone CR stays in its line and fails.
    for number, line in enumerate(text.replace("\r\n", "\n").split("\n"), start=1):
        if not line.strip(" ") or COMMENT.fullmatch(line):
            continue
        key, separator, value = line.partition(" = ")
        if not separator or not BARE_KEY.fullmatch(key) or not PLAIN_VALUE.fullmatch(value):
            problems.append(f'line {number}: not `key = "value"`: {line!r}')
        elif key not in KEYS:
            problems.append(f"line {number}: unknown key {key!r}; the keys are {list(KEYS)}")
        elif key in values:
            problems.append(f"line {number}: repeated key {key!r}")
        else:
            values[key] = value[1:-1]
    problems.extend(f"missing key {key!r}" for key in KEYS if key not in values)
    use_case = values.get("use_case")
    if use_case is not None and not PACKAGE_PATH.fullmatch(use_case):
        problems.append(
            f"use_case: {use_case!r} is not a package path under backend_logic (`notes/list`)"
        )
    summary = values.get("summary")
    if summary is not None and not summary.strip():
        problems.append("summary: empty")
    return ({} if problems else values), problems


def declaration_files(logic: Path) -> list[Path]:
    """Every file named like a declaration under logic, wherever it sits."""
    return sorted(path for path in logic.rglob(DECLARATION) if path.is_file())


def in_place(path: Path, logic: Path) -> bool:
    """`<holder>/apps/<name>/app.toml` under logic: the only place a declaration may sit."""
    parts = path.relative_to(logic).parts
    return len(parts) >= 3 and parts[-3] == CATALOGUE


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
        # Bytes, not read_text: universal newlines would turn a lone CR into a line end.
        values, own = parse_declaration(path.read_bytes().decode("utf-8"))
        problems.extend(f"{relative}: {problem}" for problem in own)
        if own:
            continue
        found.append(
            Declaration(
                path=relative,
                holder=path.parent.parent.parent.relative_to(logic.parent).as_posix(),
                name=path.parent.name,
                use_case=values["use_case"],
                summary=values["summary"],
            )
        )
    return found, problems
