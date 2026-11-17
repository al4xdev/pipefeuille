"""Read the approved deviations from docs/design/architecture-log.md.

Gates never hold a project's exceptions, so a project never edits tests/gates/ to open one.
An exception exists only if an entry under the log's "## Entries" heading has `- Exempts:` and
is approved in one of two ways (template-decisions D8). By the owner:

    - Status: approved
    - Approved by owner: YYYY-MM-DD "verbatim words of the owner"
    - Exempts: `mypy:<module pattern>`, `eager:<module>`, `suppress:<file path>`

or by the orchestrator, under a delegation the owner wrote, after an independent critic:

    - Status: approved
    - Approved by delegation: YYYY-MM-DD "verbatim words of the owner's delegation"
    - Critic: YYYY-MM-DD <who reviewed> checked <what>; verdict: approve
    - Exempts: `mypy:<module pattern>`, `eager:<module>`, `suppress:<file path>`

`mypy:` exempts a module from disallow_any_expr, `eager:` allows a top-level import without
`lazy`, `suppress:` allows `# type: ignore`, `cast(` or `# noqa` in one file. The quote is what
the owner wrote; an agent never approves its own proposal without one. A delegated entry grants
nothing without the critic's `approve`, nor when one of its tokens reaches the template's own
rules (tests/gates/, the files of TEMPLATE_SUPPORT_FILES, pyproject.toml): those change only in
the pipefeuille, by its owner. Nor when a `mypy:` pattern lifts the gate for a whole tree
(`backend_logic.*`): that loosens pyproject.toml rather than exempting one boundary module.

The reader is strict on purpose, because whatever it tolerates an agent can use to hide a grant:
- `## Entries` ends at the next heading of level 1 or 2. Fenced code and HTML comments are read
  as CommonMark renders them outside it (the entry template and the examples live there), and
  are a problem inside it: nothing in the section may be hidden from the rendered page.
- Inside an entry (a `###` heading), each field is one line at column 0 and appears at most
  once; an empty, repeated or indented field, or a `####` heading, is a problem.
- Any problem of an entry voids every token of that entry; a problem of the section itself
  (markup, an unclosed fence or comment) voids every entry of the log.
"""

import posixpath
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Literal

type ExemptionKind = Literal["mypy", "eager", "suppress"]
type EntryStatus = Literal["proposed", "approved", "rejected"]
type Approval = Literal["owner", "delegation"]

STATUSES: tuple[EntryStatus, ...] = ("proposed", "approved", "rejected")
KINDS: tuple[ExemptionKind, ...] = ("mypy", "eager", "suppress")
# ASCII digits only: `\d` would also take other scripts' digits.
DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
# `Exempts:` is either `none` or a comma-separated list of backticked tokens and nothing else.
EXEMPTS = re.compile(r"`[^`\s]+`(?:, `[^`\s]+`)*")
# Characters that render as nothing or are not text: format (zero-width spaces, bidi marks),
# control, private use, surrogates and unassigned.
INVISIBLE = frozenset({"Cf", "Cc", "Co", "Cs", "Cn"})

FIELDS = {
    "- Status:": "status",
    "- Approved by owner:": "approval",
    "- Approved by delegation:": "delegation",
    "- Critic:": "critic",
    "- Exempts:": "exempts",
}

# The template's own files in tests/support: copied into every project, never edited there,
# never opened by a delegation. This is the one list; AGENTS.md ("Who can touch what" and
# "Gates") and the README name the same set, and every tests/support module a gate imports must
# be in it (tests/gates/test_deviations.py::test_template_support_files_are_named_once). A
# project's own helpers and stubs in tests/support are not in it, so they stay delegable.
TEMPLATE_SUPPORT_FILES = (
    "architecture.py",
    "boundaries.py",
    "declarations.py",
    "deviations.py",
    "harness_agents.py",
    "tomllib.pyi",
    "yaml.pyi",
)
# What a delegation can never open, by `suppress:` path (from the project root): the gates, the
# template's support files, and the tool configuration itself.
TEMPLATE_RULE_PATHS = (
    "tests/gates/",
    *(f"tests/support/{name}" for name in TEMPLATE_SUPPORT_FILES),
    "pyproject.toml",
)
# Shell glob characters, as fnmatch reads them; mypy itself reads only a whole `*` component.
GLOB = frozenset("*?[")
ROOT = Path(__file__).resolve().parents[2]

OWNER_FIELD = '`Approved by owner: YYYY-MM-DD "..."`'
DELEGATION_FIELD = '`Approved by delegation: YYYY-MM-DD "..."`'
CRITIC_FIELD = "`Critic: YYYY-MM-DD <critic> checked <what>; verdict: approve`"


@dataclass(frozen=True)
class Exemption:
    kind: ExemptionKind
    target: str
    entry: str


@dataclass(frozen=True)
class Entry:
    title: str
    status: str
    approval: str
    exempts: tuple[str, ...]
    delegation: str = ""
    critic: str = ""
    # What the reader found wrong in the entry's lines (repeated, empty or indented fields...).
    faults: tuple[str, ...] = ()


@dataclass(frozen=True)
class Log:
    entries: tuple[Entry, ...]
    # What is wrong with the section itself; any of these voids every entry.
    faults: tuple[str, ...]


def log_path(root: Path) -> Path:
    return root / "docs" / "design" / "architecture-log.md"


def heading(raw: str) -> tuple[int, str] | None:
    """Level and text of an ATX heading (CommonMark: at most 3 spaces of indent)."""
    text = raw.lstrip(" ")
    if len(raw) - len(text) > 3:
        return None
    level = len(text) - len(text.lstrip("#"))
    rest = text[level:]
    if not 1 <= level <= 6 or (rest and not rest.startswith((" ", "\t"))):
        return None
    return level, rest.strip()


def fence_opening(raw: str) -> tuple[str, int] | None:
    """Character and length of a CommonMark code fence opened by this line."""
    text = raw.lstrip(" ")
    if len(raw) - len(text) > 3 or text[:1] not in ("`", "~"):
        return None
    mark = text[0]
    length = len(text) - len(text.lstrip(mark))
    if length < 3 or (mark == "`" and "`" in text[length:]):
        return None
    return mark, length


def fence_closes(raw: str, fence: tuple[str, int]) -> bool:
    """A closing fence: same character, at least as long, nothing after it."""
    text = raw.lstrip(" ")
    mark, length = fence
    run = len(text) - len(text.lstrip(mark))
    return len(raw) - len(text) <= 3 and run >= length and not text[run:].strip()


def without_code_spans(line: str) -> str:
    """The line without its code spans: `<!--` written as code is text, not a comment."""
    kept: list[str] = []
    position = 0
    while position < len(line):
        if line[position] != "`":
            kept.append(line[position])
            position += 1
            continue
        length = len(line[position:]) - len(line[position:].lstrip("`"))
        # A span closes at the next run of exactly as many backticks.
        search = position + length
        closing = -1
        while (found := line.find("`", search)) >= 0:
            run = len(line[found:]) - len(line[found:].lstrip("`"))
            if run == length:
                closing = found
                break
            search = found + run
        if closing < 0:
            kept.append(line[position : position + length])
            position += length
        else:
            position = closing + length
    return "".join(kept)


def comment_after(line: str, inside: bool) -> bool:
    """Whether an HTML comment is still open after this line, given whether it was before."""
    line = without_code_spans(line)
    position = 0
    while True:
        marker = "-->" if inside else "<!--"
        found = line.find(marker, position)
        if found < 0:
            return inside
        inside = not inside
        position = found + len(marker)


def read_log(text: str) -> Log:
    """Entries under "## Entries", and what is wrong with the section."""
    found: list[Entry] = []
    faults: list[str] = []
    in_section = False
    seen_section = False
    fence: tuple[str, int] | None = None
    in_comment = False
    title: str | None = None
    fields: dict[str, str] = {}
    entry_faults: list[str] = []

    def close() -> None:
        if title is None:
            return
        exempts = fields.get("exempts", "none")
        tokens: tuple[str, ...] = ()
        if exempts != "none":
            if EXEMPTS.fullmatch(exempts) is None:
                entry_faults.append(
                    f"{title}: Exempts must be `none` or backticked tokens separated by `, `"
                )
            else:
                # Backtick-delimited tokens sit at the odd positions of the split.
                tokens = tuple(exempts.split("`")[1::2])
        found.append(
            Entry(
                title,
                fields.get("status", ""),
                fields.get("approval", ""),
                tokens,
                fields.get("delegation", ""),
                fields.get("critic", ""),
                tuple(entry_faults),
            )
        )

    for number, raw in enumerate(text.splitlines(), start=1):
        # Hidden lines first, as the rendered page hides them.
        if fence is not None:
            if fence_closes(raw, fence):
                fence = None
            continue
        if in_comment:
            # Reported once, on the line that opened it.
            in_comment = comment_after(raw, inside=True)
            continue
        if (opening := fence_opening(raw)) is not None:
            fence = opening
            if in_section:
                faults.append(f"line {number}: a code fence inside `## Entries`")
            continue
        bare = without_code_spans(raw)
        if "<!--" in bare or "-->" in bare:
            in_comment = comment_after(raw, inside=False)
            if in_section:
                faults.append(f"line {number}: an HTML comment inside `## Entries`")
            continue
        if in_section and raw.lstrip().startswith(("```", "~~~")):
            faults.append(f"line {number}: a code fence inside `## Entries`")
            continue
        level_text = heading(raw)
        if level_text is not None and level_text[0] <= 2:
            close()
            title = None
            in_section = level_text == (2, "Entries")
            if in_section and seen_section:
                faults.append(f"line {number}: a second `## Entries` section")
            seen_section = seen_section or in_section
            continue
        if not in_section:
            continue
        if level_text is not None and level_text[0] == 3:
            close()
            title, fields, entry_faults = level_text[1], {}, []
            if not title:
                faults.append(f"line {number}: an entry without a title")
            continue
        if level_text is not None:
            # A `####` would read as a sub-part of the entry above, or start a hidden one.
            if title is None:
                faults.append(f"line {number}: a heading below `###` outside an entry")
            else:
                entry_faults.append(f"{title}: a heading below `###` inside an entry")
            continue
        stripped = raw.lstrip()
        for prefix, name in FIELDS.items():
            if not stripped.startswith(prefix):
                continue
            label = prefix.removeprefix("- ").removesuffix(":")
            value = stripped.removeprefix(prefix).strip()
            if title is None:
                faults.append(f"line {number}: `{label}` outside an entry")
            elif raw != stripped:
                entry_faults.append(f"{title}: `{label}` must start at column 0")
            elif name in fields:
                entry_faults.append(f"{title}: `{label}` appears more than once")
            elif not value:
                entry_faults.append(f"{title}: `{label}` is empty")
            else:
                fields[name] = value
    close()
    if fence is not None:
        faults.append("the log ends inside a code fence")
    if in_comment:
        faults.append("the log ends inside an HTML comment")
    if not seen_section:
        # Markup that hid the heading would otherwise void every approval without a word.
        faults.append("the log has no visible `## Entries` section")
    return Log(tuple(found), tuple(faults))


def entries(text: str) -> list[Entry]:
    return list(read_log(text).entries)


def visible(text: str) -> bool:
    """Has a letter or digit, and no character that renders as nothing."""
    return any(char.isalnum() for char in text) and not any(
        unicodedata.category(char) in INVISIBLE for char in text
    )


def day(text: str) -> date | None:
    """An ASCII `YYYY-MM-DD` that is a real calendar date."""
    if DATE.fullmatch(text) is None:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def quoted_on(value: str) -> date | None:
    """`YYYY-MM-DD "<words>"`: the date, when the rest is one quoted span of visible words.

    The words hold no `"` (write the owner's inner quotes as single quotes), at least three
    characters, and nothing follows the closing quote.
    """
    words = value[12:-1]
    if value[10:12] != ' "' or not value.endswith('"') or len(value) < 13:
        return None
    if '"' in words or len(words) < 3 or not visible(words):
        return None
    return day(value[:10])


def approval_is_recorded(approval: str) -> bool:
    return quoted_on(approval) is not None


def critic_review(value: str) -> tuple[date, bool] | None:
    """Date of a well-formed `Critic` and whether its verdict is approve; None if malformed.

    `<date> <critic> checked <what>; verdict: approve|reject`, with `verdict` written exactly
    once on the line and a visible critic and object.
    """
    reviewed = day(value[:10])
    rest = value[11:]
    if reviewed is None or value[10:11] != " " or rest.lower().count("verdict") != 1:
        return None
    head, separator, verdict = rest.partition("; verdict: ")
    critic, checked, what = head.partition(" checked ")
    if not separator or verdict not in ("approve", "reject") or not checked:
        return None
    if not visible(critic) or not visible(what):
        return None
    return reviewed, verdict == "approve"


def mypy_glob(pattern: str) -> re.Pattern[str]:
    """mypy's own reading of an override `module` (mypy.options.Options.compile_glob).

    A `*` component spans any number of components, at any position (`tests.*.test_style`).
    """
    parts = pattern.split(".")
    expression = ".*" if parts[0] == "*" else re.escape(parts[0])
    for part in parts[1:]:
        expression += r"(\..*)?" if part == "*" else re.escape(f".{part}")
    return re.compile(expression + r"\Z")


def template_rule_modules(root: Path) -> tuple[str, ...]:
    """Every module name under which mypy may see a file of the template's rules.

    tests/gates/ is named from the root (`tests.gates.test_style`); tests/support is on
    mypy_path, so its modules are named by file (`deviations`, and a stub by the module it
    replaces: `tomllib`) and could be named from the root too. A synthetic gate name stands for
    a gate added after this list was read.
    """
    gates = sorted(path.stem for path in (root / "tests" / "gates").glob("*.py"))
    support = tuple(name.rpartition(".")[0] for name in TEMPLATE_SUPPORT_FILES)
    return (
        "tests.gates",
        *(f"tests.gates.{name}" for name in (*gates, "test_added_later")),
        *support,
        *(f"tests.support.{name}" for name in support),
    )


def reaches_template_rules(token: str, root: Path = ROOT) -> bool:
    """Whether an Exempts token would open a file or module that holds the template's rules."""
    kind, _, target = token.partition(":")
    if kind == "suppress":
        # Normalized (`./tests/gates/x.py`), and the folder itself counts (`tests/gates`).
        return f"{posixpath.normpath(target)}/".startswith(TEMPLATE_RULE_PATHS)
    if kind == "mypy":
        inside = target.removesuffix(".*")
        glob = mypy_glob(target)
        return any(
            inside == module
            or inside.startswith(f"{module}.")
            or glob.match(module) is not None
            or glob.match(f"{module}.child") is not None
            # Stricter than mypy: a shell-style glob inside a component (`tests.g*`).
            or fnmatchcase(module, target)
            or fnmatchcase(f"{module}.child", target)
            for module in template_rule_modules(root)
        )
    return False


def covers_a_whole_tree(token: str) -> bool:
    """A `mypy:` pattern with a glob in its first two components lifts the flag for a tree.

    `backend_logic.*`, `*.parse` or `http_adapter.*.app` switch `disallow_any_expr` off for a
    whole top-level package, not one boundary module (C2): that is loosening `pyproject.toml`,
    which no delegation covers. `backend_logic.pg.*` and a bare `wire_client` are one boundary.
    """
    kind, _, target = token.partition(":")
    return kind == "mypy" and any(GLOB & set(part) for part in target.split(".")[:2])


def entry_problems(entry: Entry) -> list[str]:
    """Everything wrong with one entry; any of it voids all its tokens."""
    found = list(entry.faults)
    if entry.status not in STATUSES:
        found.append(f"{entry.title}: Status must be one of {', '.join(STATUSES)}")
    if entry.status == "approved":
        if entry.approval and entry.delegation:
            found.append(f"{entry.title}: approved both by owner and by delegation; keep one")
        elif entry.delegation:
            found.extend(delegation_problems(entry))
        elif not approval_is_recorded(entry.approval):
            found.append(f"{entry.title}: approved without {OWNER_FIELD} or {DELEGATION_FIELD}")
    for token in entry.exempts:
        kind, _, target = token.partition(":")
        if kind not in KINDS or not target:
            found.append(f"{entry.title}: unknown exemption `{token}`")
    return found


def delegation_problems(entry: Entry) -> list[str]:
    """Why an approved entry's delegation grants nothing; empty when it holds."""
    found: list[str] = []
    delegated = quoted_on(entry.delegation)
    if delegated is None:
        found.append(
            f"{entry.title}: approved by delegation without the owner's words, {DELEGATION_FIELD}"
        )
    review = critic_review(entry.critic)
    if review is None:
        found.append(f"{entry.title}: approved by delegation without {CRITIC_FIELD}")
    elif not review[1]:
        found.append(f"{entry.title}: approved by delegation, but the critic's verdict is reject")
    elif delegated is not None and review[0] < delegated:
        found.append(f"{entry.title}: the critic's review predates the owner's delegation")
    for token in entry.exempts:
        if reaches_template_rules(token):
            found.append(
                f"{entry.title}: a delegation never covers the template's own rules: `{token}`"
            )
        elif covers_a_whole_tree(token):
            found.append(
                f"{entry.title}: a delegation never lifts a gate for a whole tree: `{token}`"
            )
    return found


def approved_by(entry: Entry) -> Approval | None:
    """How a well-formed approved entry was approved; None when it grants nothing."""
    if entry.status != "approved" or entry_problems(entry):
        return None
    return "delegation" if entry.delegation else "owner"


def problems(text: str) -> list[str]:
    """Problems of the section, then of each entry, in order."""
    log = read_log(text)
    return [*log.faults, *(problem for entry in log.entries for problem in entry_problems(entry))]


def approved(text: str) -> list[Exemption]:
    """Exemptions granted by well-formed approved entries; everything else grants nothing."""
    log = read_log(text)
    if log.faults:
        return []
    granted: list[Exemption] = []
    for entry in log.entries:
        if approved_by(entry) is None:
            continue
        for token in entry.exempts:
            kind, _, target = token.partition(":")
            if kind == "mypy":
                granted.append(Exemption("mypy", target, entry.title))
            elif kind == "eager":
                granted.append(Exemption("eager", target, entry.title))
            elif kind == "suppress":
                granted.append(Exemption("suppress", target, entry.title))
    return granted


def approved_targets(root: Path, kind: ExemptionKind) -> set[str]:
    text = log_path(root).read_text(encoding="utf-8")
    return {exemption.target for exemption in approved(text) if exemption.kind == kind}
