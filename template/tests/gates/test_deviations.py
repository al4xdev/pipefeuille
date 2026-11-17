"""Guard that every exception to a gate was approved by the owner, not granted by an agent.

The deviation protocol (AGENTS.md, "Deviations"): an agent that needs to break a rule writes a
`Status: proposed` entry in docs/design/architecture-log.md with the measured cost, and stops.
Only the owner approves: in their own words, or through a written delegation quoted verbatim in
the entry and reviewed by an independent critic, which never covers the template's own rules.
The gates read the exceptions from approved entries, so opening one never means editing
tests/gates/ (template-decisions D8).
"""

import ast
import io
import tokenize
from pathlib import Path

import pytest
from deviations import approved, approved_targets, log_path, problems, reaches_template_rules

ROOT = Path(__file__).resolve().parents[2]

# Escape hatches the template itself ships, matched by path suffix so they survive a mechanism
# moving (template-decisions C2/D8). The json validator narrows to JsonValue only after a full
# recursive check; the run test calls `run` wrongly on purpose to exercise the runtime guard.
TEMPLATE_SUPPRESSIONS = (
    "_shared/json/_shared/validate/pipeline.py",
    "tests/example/test_backend_run.py",
)


def escape_hatches(source: str) -> list[str]:
    """Suppression comments, `cast` imports and `cast(...)` calls, never string contents."""
    found: list[str] = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            # mypy also honours the suppression written without spaces: compare without them.
            text = "".join(token.string.lower().split())
            if "type:ignore" in text:
                found.append(f"{token.start[0]}: type: ignore")
            if "noqa" in text:
                found.append(f"{token.start[0]}: noqa")
    for node in ast.walk(ast.parse(source)):
        # The import catches an alias (`from typing import cast as narrow`) the call would hide.
        if isinstance(node, ast.ImportFrom) and any(a.name == "cast" for a in node.names):
            found.append(f"{node.lineno}: cast import")
        if isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else None
            if isinstance(node.func, ast.Attribute):
                name = node.func.attr
            if name == "cast":
                found.append(f"{node.lineno}: cast")
    return found


def test_log_reader_grants_only_owner_approved_entries() -> None:
    log = (
        "# Architecture log\n"
        "## Entry template\n"
        "```markdown\n"
        "## Entries\n"
        "### fenced example\n"
        "- Status: approved\n"
        '- Approved by owner: 2026-01-01 "yes"\n'
        "- Exempts: `mypy:fenced.*`\n"
        "```\n"
        "<!--\n"
        "## Entries\n"
        "### commented out\n"
        "- Status: approved\n"
        '- Approved by owner: 2026-01-01 "yes"\n'
        "- Exempts: `mypy:commented.*`\n"
        "-->\n"
        "## Entries\n"
        "### proposed\n"
        "- Status: proposed\n"
        "- Exempts: `mypy:proposed.*`\n"
        "### approved without the owner's words\n"
        "- Status: approved\n"
        "- Approved by owner: 2026-01-01\n"
        "- Exempts: `eager:unquoted`\n"
        "### approved\n"
        "- Status: approved\n"
        '- Approved by owner: 2026-01-02 "ok, exempt the pg boundary"\n'
        "- Exempts: `mypy:backend_logic.pg.*`, `eager:pdfparse`\n"
        "### approved with one unknown token\n"
        "- Status: approved\n"
        '- Approved by owner: 2026-01-02 "ok, exempt both"\n'
        "- Exempts: `eager:os`, `gate:test_style.py`\n"
        "### free text\n"
        "- Status: done\n"
    )
    # Fenced and commented examples outside `## Entries` are not read; a problem anywhere in an
    # entry voids all its tokens (`eager:os` is not granted).
    assert [(e.kind, e.target) for e in approved(log)] == [
        ("mypy", "backend_logic.pg.*"),
        ("eager", "pdfparse"),
    ]
    assert problems(log) == [
        "approved without the owner's words: approved without "
        '`Approved by owner: YYYY-MM-DD "..."` or `Approved by delegation: YYYY-MM-DD "..."`',
        "approved with one unknown token: unknown exemption `gate:test_style.py`",
        "free text: Status must be one of proposed, approved, rejected",
    ]


OWNER = '- Approved by owner: 2026-03-01 "yes, exempt it"\n'
DELEGATION = '- Approved by delegation: 2026-03-01 "decide the boundaries, with a critic"\n'
CRITIC = "- Critic: 2026-03-02 critic subagent (intermediate model) checked {}; verdict: {}\n"
CRITIC_FORM = "`Critic: YYYY-MM-DD <critic> checked <what>; verdict: approve`"
OWNER_FORM = '`Approved by owner: YYYY-MM-DD "..."` or `Approved by delegation: YYYY-MM-DD "..."`'


def valid(title: str = "valid", token: str = "eager:granted") -> str:
    return f"### {title}\n- Status: approved\n{OWNER}- Exempts: `{token}`\n"


def entry(*fields: str) -> str:
    return "## Entries\n### e\n" + "".join(f"{field}\n" for field in fields)


def test_log_reader_grants_delegated_entries_only_with_quote_and_critic() -> None:
    log = (
        "## Entries\n"
        "### owner-approved\n"
        "- Status: approved\n"
        '- Approved by owner: 2026-03-01 "yes, exempt the pg boundary"\n'
        "- Exempts: `mypy:backend_logic.pg.*`\n"
        "### delegated\n"
        "- Status: approved\n"
        f"{DELEGATION}"
        f"{CRITIC.format('the measured cost and the narrowing', 'approve')}"
        "- Exempts: `eager:pdfparse`\n"
        "### delegated without critic\n"
        "- Status: approved\n"
        f"{DELEGATION}"
        "- Exempts: `eager:nocritic`\n"
        "### delegated with an unformed critic\n"
        "- Status: approved\n"
        f"{DELEGATION}"
        "- Critic: looked fine\n"
        "- Exempts: `eager:unformed`\n"
        "### delegated without the owner's words\n"
        "- Status: approved\n"
        "- Approved by delegation: 2026-03-01 owner said to go on\n"
        f"{CRITIC.format('the cost', 'approve')}"
        "- Exempts: `eager:paraphrased`\n"
        "### delegated against the critic\n"
        "- Status: approved\n"
        f"{DELEGATION}"
        f"{CRITIC.format('the cost', 'reject')}"
        "- Exempts: `eager:overruled`\n"
        "### reviewed before the delegation\n"
        "- Status: approved\n"
        f"{DELEGATION}"
        "- Critic: 2026-02-28 critic subagent checked the cost; verdict: approve\n"
        "- Exempts: `eager:early`\n"
        "### delegation reaching the template's rules\n"
        "- Status: approved\n"
        f"{DELEGATION}"
        f"{CRITIC.format('the cost', 'approve')}"
        "- Exempts: `eager:widened`, `suppress:tests/gates/test_style.py`, `mypy:tests.*`\n"
        "### both approvals\n"
        "- Status: approved\n"
        f"{OWNER}"
        f"{DELEGATION}"
        f"{CRITIC.format('the cost', 'approve')}"
        "- Exempts: `eager:both`\n"
        "### delegated but proposed\n"
        "- Status: proposed\n"
        f"{DELEGATION}"
        f"{CRITIC.format('the cost', 'approve')}"
        "- Exempts: `eager:proposed`\n"
        "### owner said no\n"
        "- Status: rejected\n"
        '- Approved by owner: 2026-03-01 "no, follow the rule"\n'
        "- Exempts: `eager:rejected`\n"
    )
    assert [(e.kind, e.target, e.entry) for e in approved(log)] == [
        ("mypy", "backend_logic.pg.*", "owner-approved"),
        ("eager", "pdfparse", "delegated"),
    ]
    assert problems(log) == [
        f"delegated without critic: approved by delegation without {CRITIC_FORM}",
        f"delegated with an unformed critic: approved by delegation without {CRITIC_FORM}",
        "delegated without the owner's words: approved by delegation without the owner's "
        'words, `Approved by delegation: YYYY-MM-DD "..."`',
        "delegated against the critic: approved by delegation, but the critic's verdict is reject",
        "reviewed before the delegation: the critic's review predates the owner's delegation",
        "delegation reaching the template's rules: a delegation never covers the template's "
        "own rules: `suppress:tests/gates/test_style.py`",
        "delegation reaching the template's rules: a delegation never covers the template's "
        "own rules: `mypy:tests.*`",
        "both approvals: approved both by owner and by delegation; keep one",
    ]


# Each case: a log, what it grants, and its exact problems. Markup the rendered page hides is
# read as CommonMark outside `## Entries` and is a problem inside it; a problem of the section
# voids every entry, a problem of an entry voids all its tokens.
HIDDEN_OR_AMBIGUOUS = {
    "comment inside Entries": (
        "## Entries\n" + valid() + "<!--\n" + valid("hidden", "eager:hidden") + "-->\n",
        [],
        ["line 6: an HTML comment inside `## Entries`"],
    ),
    "comment on an Exempts line": (
        entry("- Status: approved", OWNER.strip(), "- Exempts: `eager:x` <!-- `eager:y` -->"),
        [],
        ["line 5: an HTML comment inside `## Entries`"],
    ),
    "fence inside Entries": (
        "## Entries\n" + valid() + "~~~\n" + valid("fenced", "eager:fenced") + "~~~\n",
        [],
        ["line 6: a code fence inside `## Entries`"],
    ),
    "a shorter fence does not close a longer one": (
        "````\n```\n## Entries\n" + valid() + "````\n",
        [],
        ["the log has no visible `## Entries` section"],
    ),
    "a tilde line does not close a backtick fence": (
        "```\n~~~\n```\n## Entries\n" + valid(),
        ["eager:granted"],
        [],
    ),
    "a comment opened after a closed one on the same line": (
        "<!-- closed --> <!-- open\n## Entries\n" + valid() + "-->\n",
        [],
        ["the log has no visible `## Entries` section"],
    ),
    "a comment marker written as code is text": (
        "Skip `<!--` lines.\n## Entries\n"
        + valid()
        + "- Decision and reason: drop the `-->` hack\n",
        ["eager:granted"],
        [],
    ),
    "a real comment and a marker written as code on one line": (
        "Note <!-- a real one --> and `<!--` as code.\n## Entries\n" + valid(),
        ["eager:granted"],
        [],
    ),
    "no Entries section": (
        "# Architecture log\n" + valid(),
        [],
        ["the log has no visible `## Entries` section"],
    ),
    "a level-1 heading ends Entries": (
        "## Entries\n" + valid() + "# Appendix\n" + valid("after", "eager:after"),
        ["eager:granted"],
        [],
    ),
    "unclosed fence": (
        "## Entries\n" + valid() + "## Notes\n```\n",
        [],
        ["the log ends inside a code fence"],
    ),
    "unclosed comment": (
        "## Entries\n" + valid() + "## Notes\n<!--\n",
        [],
        ["the log ends inside an HTML comment"],
    ),
    "second Entries section": (
        "## Entries\n" + valid() + "## Entries\n" + valid("again", "eager:again"),
        [],
        ["line 6: a second `## Entries` section"],
    ),
    "heading below ### inside an entry": (
        "## Entries\n" + valid() + "#### sub\n",
        [],
        ["valid: a heading below `###` inside an entry"],
    ),
    "field before any entry": (
        "## Entries\n- Status: approved\n" + valid(),
        [],
        ["line 2: `Status` outside an entry"],
    ),
    "repeated Status": (
        entry("- Status: proposed", "- Status: approved", OWNER.strip(), "- Exempts: `eager:x`"),
        [],
        ["e: `Status` appears more than once"],
    ),
    "empty field next to an owner approval": (
        entry(
            "- Status: approved",
            OWNER.strip(),
            "- Approved by delegation:",
            "- Exempts: `suppress:tests/gates/test_style.py`",
        ),
        [],
        ["e: `Approved by delegation` is empty"],
    ),
    "repeated Critic": (
        entry(
            "- Status: approved",
            DELEGATION.strip(),
            CRITIC.format("a", "reject").strip(),
            CRITIC.format("a", "approve").strip(),
            "- Exempts: `eager:x`",
        ),
        [],
        [
            "e: `Critic` appears more than once",
            "e: approved by delegation, but the critic's verdict is reject",
        ],
    ),
    "two verdicts on one Critic line": (
        entry(
            "- Status: approved",
            DELEGATION.strip(),
            "- Critic: 2026-03-02 critic checked x; verdict: reject; verdict: approve",
            "- Exempts: `eager:x`",
        ),
        [],
        [f"e: approved by delegation without {CRITIC_FORM}"],
    ),
    "indented field": (
        entry("- Status: approved", f"  {OWNER.strip()}", "- Exempts: `eager:x`"),
        [],
        ["e: `Approved by owner` must start at column 0", f"e: approved without {OWNER_FORM}"],
    ),
    "Exempts with prose": (
        entry("- Status: approved", OWNER.strip(), "- Exempts: `eager:x` and more"),
        [],
        ["e: Exempts must be `none` or backticked tokens separated by `, `"],
    ),
    "Exempts with an unclosed backtick": (
        entry("- Status: approved", OWNER.strip(), "- Exempts: `eager:x`, `eager:y"),
        [],
        ["e: Exempts must be `none` or backticked tokens separated by `, `"],
    ),
    "Exempts none with a note": (
        entry("- Status: approved", OWNER.strip(), "- Exempts: none (a note)"),
        [],
        ["e: Exempts must be `none` or backticked tokens separated by `, `"],
    ),
    "Exempts none": (
        entry("- Status: approved", OWNER.strip(), "- Exempts: none"),
        [],
        [],
    ),
    "non-ASCII digits in the Critic date": (
        entry(
            "- Status: approved",
            DELEGATION.strip(),
            "- Critic: ٢٠٢٠-٠١-٠١ critic checked x; verdict: approve",
            "- Exempts: `eager:x`",
        ),
        [],
        [f"e: approved by delegation without {CRITIC_FORM}"],
    ),
    "a date that does not exist": (
        entry(
            "- Status: approved", '- Approved by owner: 2026-99-99 "yes"', "- Exempts: `eager:x`"
        ),
        [],
        [f"e: approved without {OWNER_FORM}"],
    ),
    "an ISO week date is not a calendar day": (
        entry(
            "- Status: approved", '- Approved by owner: 2026-W10-1 "yes"', "- Exempts: `eager:x`"
        ),
        [],
        [f"e: approved without {OWNER_FORM}"],
    ),
    "blank quote": (
        entry(
            "- Status: approved", '- Approved by owner: 2026-03-01 "   "', "- Exempts: `eager:x`"
        ),
        [],
        [f"e: approved without {OWNER_FORM}"],
    ),
    "two quoted spans": (
        entry(
            "- Status: approved",
            '- Approved by owner: 2026-03-01 "a" unquoted "b"',
            "- Exempts: `eager:x`",
        ),
        [],
        [f"e: approved without {OWNER_FORM}"],
    ),
    "no space before the quote": (
        entry("- Status: approved", '- Approved by owner: 2026-03-01"yes"', "- Exempts: `eager:x`"),
        [],
        [f"e: approved without {OWNER_FORM}"],
    ),
    "zero-width critic and object": (
        entry(
            "- Status: approved",
            DELEGATION.strip(),
            "- Critic: 2026-03-02 \u200b checked \u200b; verdict: approve",
            "- Exempts: `eager:x`",
        ),
        [],
        [f"e: approved by delegation without {CRITIC_FORM}"],
    ),
}


@pytest.mark.parametrize("case", HIDDEN_OR_AMBIGUOUS)
def test_log_reader_voids_hidden_repeated_or_malformed_lines(case: str) -> None:
    log, granted, expected = HIDDEN_OR_AMBIGUOUS[case]
    assert [f"{e.kind}:{e.target}" for e in approved(log)] == granted
    assert problems(log) == expected


def test_template_rule_reach_sees_paths_and_wider_patterns() -> None:
    tokens = [
        "suppress:tests/gates/test_config.py",
        "suppress:tests/gates",
        "suppress:./tests/gates/test_style.py",
        "suppress:tests//gates/test_style.py",
        "suppress:tests/support/deviations.py",
        "suppress:tests/support/wire_client.py",
        "suppress:tests/gates_extra/x.py",
        "suppress:http_adapter/app.py",
        "mypy:tests.gates.test_style",
        "mypy:tests.gates.*",
        "mypy:tests.gates.test_added_later",
        "mypy:tests.*",
        "mypy:*",
        "mypy:tests.*.test_style",
        "mypy:tests.*.gates.test_style",
        "mypy:*.test_deviations",
        "mypy:tests.support.*",
        "mypy:*.deviations",
        "mypy:tests.support.deviations",
        "mypy:deviations",
        "mypy:architecture.*",
        "mypy:tests.g*",
        "mypy:tests.notes.*",
        "mypy:*.notes.*",
        "mypy:wire_client",
        "mypy:backend_logic.*",
        "eager:tests.gates",
    ]
    assert [token for token in tokens if reaches_template_rules(token)] == [
        "suppress:tests/gates/test_config.py",
        "suppress:tests/gates",
        "suppress:./tests/gates/test_style.py",
        "suppress:tests//gates/test_style.py",
        "suppress:tests/support/deviations.py",
        "mypy:tests.gates.test_style",
        "mypy:tests.gates.*",
        "mypy:tests.gates.test_added_later",
        "mypy:tests.*",
        "mypy:*",
        "mypy:tests.*.test_style",
        "mypy:tests.*.gates.test_style",
        "mypy:*.test_deviations",
        "mypy:tests.support.*",
        "mypy:*.deviations",
        "mypy:tests.support.deviations",
        "mypy:deviations",
        "mypy:architecture.*",
        "mypy:tests.g*",
    ]


def test_architecture_log_is_well_formed() -> None:
    assert not problems(log_path(ROOT).read_text(encoding="utf-8"))


def test_escape_hatch_scanner_ignores_strings() -> None:
    source = (
        "from typing import cast\n"
        "x = cast(int, y)  # type: ignore[misc]\n"
        "z = typing.cast(int, y)  # noqa: E501\n"
        "s = '# type: ignore and cast(a, b) # noqa'\n"
        "from typing import cast as narrow\n"
        "w = narrow(int, y)  #type:ignore\n"
    )
    assert escape_hatches(source) == [
        "2: type: ignore",
        "3: noqa",
        "6: type: ignore",
        "1: cast import",
        "5: cast import",
        "2: cast",
        "3: cast",
    ]


def project_files(name: str) -> list[Path]:
    """Every file with this name pattern, outside dot folders (.venv, .data, .dumps, caches)."""
    return sorted(
        path
        for path in ROOT.rglob(name)
        if not any(part.startswith(".") for part in path.relative_to(ROOT).parts)
    )


COLLECTION_HOOKS = {
    "pytest_collection_modifyitems",
    "pytest_ignore_collect",
    "pytest_collection",
    "pytest_collect_file",
    "pytest_runtest_setup",
}


def collection_hooks(source: str) -> list[str]:
    """Pytest hooks that can skip or drop tests before they run."""
    return [
        node.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and node.name in COLLECTION_HOOKS
    ]


def test_collection_hook_scanner_reports_every_hook() -> None:
    source = (
        "def pytest_collection_modifyitems(items): ...\n"
        "def pytest_ignore_collect(collection_path): ...\n"
        "def fixture_helper(): ...\n"
    )
    assert collection_hooks(source) == [
        "pytest_collection_modifyitems",
        "pytest_ignore_collect",
    ]


def test_no_conftest_can_drop_a_gate() -> None:
    # A conftest that deselects or skips tests switches a gate off without touching it.
    violations = [
        f"{path.relative_to(ROOT)}: {hook}"
        for path in project_files("conftest.py")
        for hook in collection_hooks(path.read_text(encoding="utf-8"))
    ]
    assert not violations, "fixtures may live in conftest.py; collection hooks may not"


def test_escape_hatches_only_where_the_owner_approved() -> None:
    # §6: a cast or a suppression comment hides a contract from the gate that would catch it.
    # Every Python file of the project counts, not only backend_logic, http_adapter and tests.
    allowed = approved_targets(ROOT, "suppress")
    violations = [
        f"{relative}:{hit}"
        for path in project_files("*.py")
        if not (relative := path.relative_to(ROOT).as_posix()).endswith(TEMPLATE_SUPPRESSIONS)
        and relative not in allowed
        for hit in escape_hatches(path.read_text(encoding="utf-8"))
    ]
    assert not violations, "fix the contract, or propose `suppress:<file>` (AGENTS.md, Deviations)"
