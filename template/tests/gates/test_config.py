"""Guard the gate configuration that ships with the template.

This module is checked by the same mypy it guards, with no Any in any expression: tomllib is
read through the stub tests/support/tomllib.pyi (values typed `object`), and every value is
narrowed with isinstance before any comparison (docs/design/template-decisions.md, C2).

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
    # A1: no __init__.py, so modules are named from the root; without this, two `run.py`
    # files collide as the same module and mypy stops before checking anything.
    "explicit_package_bases",
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
# The template has no Any boundary (C2): every override of disallow_any_expr must be named by
# an owner-approved `mypy:<module>` entry of architecture-log.md (D8).


def table(value: object, name: str) -> dict[str, object]:
    """A TOML table with its keys as str. isinstance alone would narrow to dict[Any, Any]."""
    if not isinstance(value, dict):
        raise TypeError(f"pyproject [{name}] must be a table")
    return {str(key): item for key, item in value.items()}


def tool_section(name: str) -> dict[str, object]:
    document = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return table(table(document["tool"], "tool")[name], f"tool.{name}")


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
    formatter = table(ruff["format"], "tool.ruff.format")
    # Exactly these: anything more would take code out of the formatter.
    assert strings(formatter["exclude"]) == {"backend_logic/**/run.py", "docs/**/*.md"}


def test_ruff_rules_are_never_switched_off() -> None:
    ruff = tool_section("ruff")
    assert isinstance(ruff["line-length"], int)
    assert ruff["line-length"] <= 100
    lint = table(ruff["lint"], "tool.ruff.lint")
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
    options = table(pytest["ini_options"], "tool.pytest.ini_options")
    assert strings(options["testpaths"]) == {"tests"}
    addopts = options["addopts"]
    assert isinstance(addopts, str)
    narrowing = ("--ignore", "--deselect", "-k", "-p", "--co", "--collect-only", "--lf")
    found = [token for token in addopts.split() if token.startswith(narrowing)]
    assert not found, f"pytest options may not narrow collection: {found}"


def test_mypy_gate_keeps_any_out_of_expressions_everywhere() -> None:
    # §6: disallow_any_expr is global; only owner-approved boundaries lift it.
    mypy = tool_section("mypy")
    for flag in MYPY_FLAGS:
        assert mypy[flag] is True, flag
    assert strings(mypy["enable_error_code"]) >= MYPY_ERROR_CODES
    # Code is never excluded from the checker, and no global switch hides errors.
    assert strings(mypy["exclude"]) == {"^\\.data/", "^\\.dumps/"}
    # Another root would rename modules and slip them past the override names below.
    assert strings(mypy["mypy_path"]) == {"tests/support"}
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
    # The template ships no override: the key exists only once an approved entry needs one.
    overrides = mypy.get("overrides", [])
    if not isinstance(overrides, list):
        raise TypeError("pyproject [[tool.mypy.overrides]] must be an array of tables")
    exempt: set[str] = set()
    for entry in overrides:
        override = table(entry, "tool.mypy.overrides")
        # An override may only lift disallow_any_expr: no ignore_errors, no follow_imports.
        assert set(override) == {"module", "disallow_any_expr"}, sorted(override)
        assert override["disallow_any_expr"] is False
        exempt |= strings(override["module"])
    approved = approved_targets(ROOT, "mypy")
    unapproved = sorted(module for module in exempt if module not in approved)
    assert not unapproved, f"propose `mypy:<module>` (AGENTS.md, Deviations): {unapproved}"
