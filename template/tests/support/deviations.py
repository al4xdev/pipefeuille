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
`lazy`, `suppress:` allows `# type: ignore`, `cast(` or `# noqa` in one file. A proposed or
rejected entry grants nothing, and fenced code (the entry template and the example) is never
read. The quote is what the owner wrote; an agent never approves its own proposal without one.
A delegated entry grants nothing without the critic's `approve`, nor when one of its tokens
reaches the template's own rules (tests/gates/, tests/support/deviations.py,
tests/support/architecture.py): those change only in the pipefeuille, by its owner.
"""

import re
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Literal

type ExemptionKind = Literal["mypy", "eager", "suppress"]
type EntryStatus = Literal["proposed", "approved", "rejected"]
type Approval = Literal["owner", "delegation"]

STATUSES: tuple[EntryStatus, ...] = ("proposed", "approved", "rejected")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
# `<date> <critic> checked <what>; verdict: approve|reject`. The "checked" clause makes the
# writer name the critic and what it reviewed; the verdict closes the line.
CRITIC = re.compile(r"(\d{4}-\d{2}-\d{2}) (\S.*?) checked (\S.*); verdict: (approve|reject)")

# What a delegation can never open: the files that hold the template's rules, by `suppress:`
# path (from the project root) and by `mypy:` module (tests/support is on mypy_path, so its
# modules are named by file).
TEMPLATE_RULE_PATHS = (
    "tests/gates/",
    "tests/support/deviations.py",
    "tests/support/architecture.py",
)
TEMPLATE_RULE_MODULES = ("tests.gates", "deviations", "architecture")

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


def log_path(root: Path) -> Path:
    return root / "docs" / "design" / "architecture-log.md"


FIELDS = {
    "- Status:": "status",
    "- Approved by owner:": "approval",
    "- Approved by delegation:": "delegation",
    "- Critic:": "critic",
}


def entries(text: str) -> list[Entry]:
    """Entries under "## Entries", outside code fences and HTML comments."""
    found: list[Entry] = []
    in_section = False
    in_fence = False
    in_comment = False
    title: str | None = None
    fields: dict[str, str] = {}
    exempts: list[str] = []

    def close() -> None:
        if title is not None:
            found.append(
                Entry(
                    title,
                    fields.get("status", ""),
                    fields.get("approval", ""),
                    tuple(exempts),
                    fields.get("delegation", ""),
                    fields.get("critic", ""),
                )
            )

    for raw in text.splitlines():
        line = raw.strip()
        # Nothing the rendered page hides can grant: fenced code (either fence) and HTML
        # comments, including a comment that spans lines.
        if in_comment:
            in_comment = "-->" not in line
            continue
        if line.startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if line.startswith("<!--"):
            in_comment = "-->" not in line
            continue
        if line.startswith("## "):
            close()
            title = None
            in_section = line == "## Entries"
            continue
        if not in_section:
            continue
        if line.startswith("### "):
            close()
            title, fields, exempts = line[4:].strip(), {}, []
        elif title is not None and line.startswith("- Exempts:"):
            # Backtick-delimited tokens sit at the odd positions of the split.
            exempts.extend(line.split("`")[1::2])
        elif title is not None:
            for prefix, name in FIELDS.items():
                if line.startswith(prefix):
                    fields[name] = line.removeprefix(prefix).strip()
    close()
    return found


def approval_is_recorded(approval: str) -> bool:
    """A date, then the owner's words in double quotes."""
    quoted = approval[10:].strip()
    return (
        DATE.fullmatch(approval[:10]) is not None
        and len(quoted) > 4
        and quoted.startswith('"')
        and quoted.endswith('"')
    )


def reaches_template_rules(token: str) -> bool:
    """Whether an Exempts token would open a file or module that holds the template's rules."""
    kind, _, target = token.partition(":")
    if kind == "suppress":
        # The trailing slash also catches the folder itself (`suppress:tests/gates`).
        return f"{target}/".startswith(TEMPLATE_RULE_PATHS)
    if kind == "mypy":
        inside = target.removesuffix(".*")
        return any(
            inside == module
            or inside.startswith(f"{module}.")
            # A wider pattern (`tests.*`, `*`) covers the module or one of its submodules.
            or fnmatchcase(module, target)
            or fnmatchcase(f"{module}.x", target)
            for module in TEMPLATE_RULE_MODULES
        )
    return False


def delegation_problems(entry: Entry) -> list[str]:
    """Why an approved entry's delegation grants nothing; empty when it holds."""
    found: list[str] = []
    if not approval_is_recorded(entry.delegation):
        found.append(
            f"{entry.title}: approved by delegation without the owner's words, {DELEGATION_FIELD}"
        )
    # The shape comes from the regex; its groups are typed `str | Any`, so the verdict and the
    # date are read by position instead (the shape already fixed both).
    if CRITIC.fullmatch(entry.critic) is None:
        found.append(f"{entry.title}: approved by delegation without {CRITIC_FIELD}")
    elif not entry.critic.endswith("; verdict: approve"):
        found.append(f"{entry.title}: approved by delegation, but the critic's verdict is reject")
    elif entry.critic[:10] < entry.delegation[:10]:
        found.append(f"{entry.title}: the critic's review predates the owner's delegation")
    found.extend(
        f"{entry.title}: a delegation never covers the template's own rules: `{token}`"
        for token in entry.exempts
        if reaches_template_rules(token)
    )
    return found


def approved_by(entry: Entry) -> Approval | None:
    """How a well-formed approved entry was approved; None when it grants nothing."""
    if entry.status != "approved":
        return None
    if entry.delegation:
        # Both fields at once leaves it unclear who decided: the entry grants nothing.
        if entry.approval or delegation_problems(entry):
            return None
        return "delegation"
    return "owner" if approval_is_recorded(entry.approval) else None


def problems(text: str) -> list[str]:
    """Malformed entries: unknown status, approval not recorded as D8 asks, unknown kind."""
    found: list[str] = []
    for entry in entries(text):
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
            if kind not in ("mypy", "eager", "suppress") or not target:
                found.append(f"{entry.title}: unknown exemption `{token}`")
    return found


def approved(text: str) -> list[Exemption]:
    """Exemptions granted by well-formed approved entries; everything else grants nothing."""
    granted: list[Exemption] = []
    for entry in entries(text):
        if approved_by(entry) is None:
            continue
        for token in entry.exempts:
            kind, _, target = token.partition(":")
            if not target:
                continue
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
