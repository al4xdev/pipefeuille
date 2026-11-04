"""Read the owner-approved deviations from docs/design/architecture-log.md.

Gates never hold a project's exceptions, so a project never edits tests/gates/ to open one.
An exception exists only if an entry under the log's "## Entries" heading has all of:

    - Status: approved
    - Approved by owner: YYYY-MM-DD "verbatim words of the owner"
    - Exempts: `mypy:<module pattern>`, `eager:<module>`, `suppress:<file path>`

`mypy:` exempts a module from disallow_any_expr, `eager:` allows a top-level import without
`lazy`, `suppress:` allows `# type: ignore`, `cast(` or `# noqa` in one file. A proposed or
rejected entry grants nothing, and fenced code (the entry template and the example) is never
read. The quote is what the owner wrote; an agent never approves its own proposal.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

type ExemptionKind = Literal["mypy", "eager", "suppress"]
type EntryStatus = Literal["proposed", "approved", "rejected"]

STATUSES: tuple[EntryStatus, ...] = ("proposed", "approved", "rejected")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


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


def log_path(root: Path) -> Path:
    return root / "docs" / "design" / "architecture-log.md"


def entries(text: str) -> list[Entry]:
    """Entries under "## Entries", outside code fences and HTML comments."""
    found: list[Entry] = []
    in_section = False
    in_fence = False
    in_comment = False
    title: str | None = None
    status = approval = ""
    exempts: list[str] = []

    def close() -> None:
        if title is not None:
            found.append(Entry(title, status, approval, tuple(exempts)))

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
            title, status, approval, exempts = line[4:].strip(), "", "", []
        elif title is not None and line.startswith("- Status:"):
            status = line.removeprefix("- Status:").strip()
        elif title is not None and line.startswith("- Approved by owner:"):
            approval = line.removeprefix("- Approved by owner:").strip()
        elif title is not None and line.startswith("- Exempts:"):
            # Backtick-delimited tokens sit at the odd positions of the split.
            exempts.extend(line.split("`")[1::2])
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


def problems(text: str) -> list[str]:
    """Malformed entries: unknown status, approval without the owner's words, unknown kind."""
    found: list[str] = []
    for entry in entries(text):
        if entry.status not in STATUSES:
            found.append(f"{entry.title}: Status must be one of {', '.join(STATUSES)}")
        if entry.status == "approved" and not approval_is_recorded(entry.approval):
            found.append(f'{entry.title}: approved without `Approved by owner: YYYY-MM-DD "..."`')
        for token in entry.exempts:
            kind, _, target = token.partition(":")
            if kind not in ("mypy", "eager", "suppress") or not target:
                found.append(f"{entry.title}: unknown exemption `{token}`")
    return found


def approved(text: str) -> list[Exemption]:
    """Exemptions granted by well-formed approved entries; everything else grants nothing."""
    granted: list[Exemption] = []
    for entry in entries(text):
        if entry.status != "approved" or not approval_is_recorded(entry.approval):
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
