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
        "```markdown\n"
        "## Entries\n"
        "### fenced example\n"
        "- Status: approved\n"
        '- Approved by owner: 2026-01-01 "yes"\n'
        "- Exempts: `mypy:fenced.*`\n"
        "```\n"
        "## Entries\n"
        "<!--\n"
        "### hidden in a comment\n"
        "- Status: approved\n"
        '- Approved by owner: 2026-01-01 "yes"\n'
        "- Exempts: `mypy:commented.*`\n"
        "-->\n"
        "~~~\n"
        "### hidden in a tilde fence\n"
        "- Status: approved\n"
        '- Approved by owner: 2026-01-01 "yes"\n'
        "- Exempts: `mypy:tilde.*`\n"
        "~~~\n"
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
        "- Exempts: `mypy:backend_logic.pg.*`, `eager:pdfparse`, `gate:test_style.py`\n"
        "### free text\n"
        "- Status: done\n"
    )
    assert [(e.kind, e.target) for e in approved(log)] == [
        ("mypy", "backend_logic.pg.*"),
        ("eager", "pdfparse"),
    ]
    assert problems(log) == [
        "approved without the owner's words: approved without "
        '`Approved by owner: YYYY-MM-DD "..."` or `Approved by delegation: YYYY-MM-DD "..."`',
        "approved: unknown exemption `gate:test_style.py`",
        "free text: Status must be one of proposed, approved, rejected",
    ]


DELEGATION = '- Approved by delegation: 2026-03-01 "decide the boundaries, with a critic"\n'
CRITIC = "- Critic: 2026-03-02 critic subagent (intermediate model) checked {}; verdict: {}\n"


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
        '- Approved by owner: 2026-03-01 "yes, exempt it"\n'
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
    critic_form = "`Critic: YYYY-MM-DD <critic> checked <what>; verdict: approve`"
    assert problems(log) == [
        f"delegated without critic: approved by delegation without {critic_form}",
        f"delegated with an unformed critic: approved by delegation without {critic_form}",
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


def test_template_rule_reach_sees_paths_and_wider_patterns() -> None:
    tokens = [
        "suppress:tests/gates/test_config.py",
        "suppress:tests/gates",
        "suppress:tests/support/deviations.py",
        "suppress:tests/support/wire_client.py",
        "suppress:tests/gates_extra/x.py",
        "suppress:http_adapter/app.py",
        "mypy:tests.gates.test_style",
        "mypy:tests.gates.*",
        "mypy:tests.*",
        "mypy:*",
        "mypy:deviations",
        "mypy:architecture.*",
        "mypy:tests.notes.*",
        "mypy:backend_logic.*",
        "eager:tests.gates",
    ]
    assert [token for token in tokens if reaches_template_rules(token)] == [
        "suppress:tests/gates/test_config.py",
        "suppress:tests/gates",
        "suppress:tests/support/deviations.py",
        "mypy:tests.gates.test_style",
        "mypy:tests.gates.*",
        "mypy:tests.*",
        "mypy:*",
        "mypy:deviations",
        "mypy:architecture.*",
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
