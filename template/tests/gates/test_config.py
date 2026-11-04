"""Guard the gate configuration that ships with the template.

This is the one test module allowed to hold Any: tomllib returns dict[str, Any] and has no
typed alternative. Values are narrowed with isinstance before any comparison, and the
pyproject override exempting this module is explained in docs/design/template-decisions.md (C2).
"""

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def tool_section(name: str) -> dict[str, object]:
    document = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    tool = document["tool"]
    if not isinstance(tool, dict):
        raise TypeError("pyproject [tool] must be a table")
    section = tool[name]
    if not isinstance(section, dict):
        raise TypeError(f"pyproject [tool.{name}] must be a table")
    return {str(key): value for key, value in section.items()}


def test_run_composition_is_left_to_the_author_not_the_formatter() -> None:
    # §4.1: the formatter skips run.py; force-exclude keeps editors that pass a path from
    # reformatting it anyway.
    ruff = tool_section("ruff")
    assert ruff["force-exclude"] is True
    formatter = ruff["format"]
    assert isinstance(formatter, dict)
    excluded = formatter["exclude"]
    assert isinstance(excluded, list)
    assert {"backend_logic/**/run.py", "docs/**/*.md"} <= {str(item) for item in excluded}


def test_mypy_gate_keeps_any_out_of_expressions_everywhere() -> None:
    # §6: disallow_any_expr is global; only recorded boundaries may switch it off.
    mypy = tool_section("mypy")
    assert mypy["strict"] is True
    assert mypy["disallow_any_expr"] is True
    assert mypy["warn_unreachable"] is True
    overrides = mypy["overrides"]
    assert isinstance(overrides, list)
    exempt = sorted(
        str(module)
        for override in overrides
        if isinstance(override, dict) and override.get("disallow_any_expr") is False
        for module in (override["module"] if isinstance(override["module"], list) else [])
    )
    assert exempt == ["backend_logic._shared.json.decode.*", "test_config", "wire_client"]
