"""Guard the gate configuration that ships with the template.

This is the one test module allowed to hold Any: tomllib returns dict[str, Any] and has no
typed alternative. Values are narrowed with isinstance before any comparison, and the
pyproject override exempting this module is explained in docs/design/template-decisions.md (C2).

The configuration may be tightened freely. Loosening it is a deviation: the project never
edits this file; the owner approves a `mypy:<module>` entry in architecture-log.md instead
(AGENTS.md, "Deviations"; template-decisions D8).
"""

import tomllib
from pathlib import Path

from deviations import approved_targets

ROOT = Path(__file__).resolve().parents[2]

RUFF_RULES = {"E", "F", "I", "N", "W", "UP", "B", "C4", "SIM"}
MYPY_FLAGS = (
    "strict",
    "disallow_any_explicit",
    "disallow_any_unimported",
    "disallow_any_expr",
    "warn_unreachable",
    "strict_bytes",
)
MYPY_ERROR_CODES = {
    "ignore-without-code",
    "redundant-expr",
    "redundant-self",
    "truthy-bool",
    "truthy-iterable",
    "possibly-undefined",
    "unused-awaitable",
    "explicit-override",
    "mutable-override",
    "exhaustive-match",
    "deprecated",
}
# The template's three Any boundaries (C2). The json decoder is matched by suffix so it may
# move with the mechanism (guide §2, `_shared/` block) without a gate edit.
TEMPLATE_BOUNDARY_SUFFIX = "_shared.json.decode.*"
TEMPLATE_TEST_BOUNDARIES = {"test_config", "wire_client"}


def tool_section(name: str) -> dict[str, object]:
    document = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    tool = document["tool"]
    if not isinstance(tool, dict):
        raise TypeError("pyproject [tool] must be a table")
    section = tool[name]
    if not isinstance(section, dict):
        raise TypeError(f"pyproject [tool.{name}] must be a table")
    return {str(key): value for key, value in section.items()}


def strings(value: object) -> set[str]:
    if not isinstance(value, list):
        raise TypeError("expected a list")
    return {str(item) for item in value}


# Each of these takes precedence over pyproject.toml for its tool (and ruff uses the nearest
# config in the tree), so any of them would replace the gate configuration silently.
PARALLEL_CONFIGS = {
    "ruff.toml",
    ".ruff.toml",
    "mypy.ini",
    ".mypy.ini",
    "setup.cfg",
    "pytest.ini",
    ".pytest.ini",
    "tox.ini",
    "pyproject.toml",
}


def test_pyproject_is_the_only_tool_configuration() -> None:
    parallel = sorted(
        relative.as_posix()
        for path in ROOT.rglob("*")
        if path.name in PARALLEL_CONFIGS
        and (relative := path.relative_to(ROOT)) != Path("pyproject.toml")
        and not any(part.startswith(".") for part in relative.parts[:-1])
    )
    assert not parallel, f"configure tools only in the root pyproject.toml: {parallel}"


def test_run_composition_is_left_to_the_author_not_the_formatter() -> None:
    # §4.1: the formatter skips run.py; force-exclude keeps editors that pass a path from
    # reformatting it anyway.
    ruff = tool_section("ruff")
    assert ruff["force-exclude"] is True
    formatter = ruff["format"]
    assert isinstance(formatter, dict)
    # Exactly these: anything more would take code out of the formatter.
    assert strings(formatter["exclude"]) == {"backend_logic/**/run.py", "docs/**/*.md"}


def test_ruff_rules_are_never_switched_off() -> None:
    ruff = tool_section("ruff")
    assert isinstance(ruff["line-length"], int)
    assert ruff["line-length"] <= 100
    lint = ruff["lint"]
    assert isinstance(lint, dict)
    assert strings(lint["select"]) >= RUFF_RULES
    loosening = {"ignore", "extend-ignore", "per-file-ignores", "unfixable"} & set(lint)
    loosening |= {"exclude", "extend-exclude"} & set(lint)
    loosening |= {"exclude"} & set(ruff)
    assert not loosening, f"ruff rules are tightened, never ignored: {sorted(loosening)}"
    # Only private data and scratch stay outside the linter; code never does.
    assert strings(ruff["extend-exclude"]) == {".data", ".dumps"}


def test_pytest_collects_every_test_folder() -> None:
    # A gate that is never collected is a gate switched off.
    pytest = tool_section("pytest")
    options = pytest["ini_options"]
    assert isinstance(options, dict)
    assert strings(options["testpaths"]) == {"tests"}
    addopts = options["addopts"]
    assert isinstance(addopts, str)
    narrowing = ("--ignore", "--deselect", "-k", "-p", "--co", "--collect-only", "--lf")
    found = [token for token in addopts.split() if token.startswith(narrowing)]
    assert not found, f"pytest options may not narrow collection: {found}"


def test_mypy_gate_keeps_any_out_of_expressions_everywhere() -> None:
    # §6: disallow_any_expr is global; only template or owner-approved boundaries lift it.
    mypy = tool_section("mypy")
    for flag in MYPY_FLAGS:
        assert mypy[flag] is True, flag
    assert strings(mypy["enable_error_code"]) >= MYPY_ERROR_CODES
    # Code is never excluded from the checker, and no global switch hides errors.
    assert strings(mypy["exclude"]) == {"^\\.data/", "^\\.dumps/"}
    hiding = {
        "ignore_errors",
        "ignore_missing_imports",
        "follow_imports",
        "disable_error_code",
        "files",
        "packages",
        "modules",
    } & set(mypy)
    assert not hiding, f"mypy may not be narrowed or silenced globally: {sorted(hiding)}"
    overrides = mypy["overrides"]
    assert isinstance(overrides, list)
    exempt: set[str] = set()
    for override in overrides:
        assert isinstance(override, dict)
        # An override may only lift disallow_any_expr: no ignore_errors, no follow_imports.
        assert set(override) == {"module", "disallow_any_expr"}, sorted(override)
        assert override["disallow_any_expr"] is False
        exempt |= strings(override["module"])
    approved = approved_targets(ROOT, "mypy")
    unapproved = sorted(
        module
        for module in exempt
        if not module.endswith(TEMPLATE_BOUNDARY_SUFFIX)
        and module not in TEMPLATE_TEST_BOUNDARIES
        and module not in approved
    )
    assert not unapproved, f"propose `mypy:<module>` (AGENTS.md, Deviations): {unapproved}"
