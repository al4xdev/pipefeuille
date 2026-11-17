"""Which libraries the code may use, how it loads them, and the stubs that type them.

- A third-party import in `backend_logic` or `http_adapter` names a library of the
  `[project] dependencies` of pyproject.toml, extras included (support/boundaries.py reads them
  from the installed metadata). A library that is only installed (a transitive dependency, a
  dev tool such as httpx) is not granted: declaring it is what grants the import.
- Nothing in that code calls `importlib.import_module` or `__import__`, or holds a reference
  to them: every library is a plain import that mypy sees, typed by the library or by a stub.
  A module loaded by string hides a rename from the checker and its Any from
  disallow_any_expr, so there is no allowlist and no log token for it.
- Every typed stub in tests/support (on mypy_path, so it replaces the library's own types)
  declares only names, bases, parameters and attributes the installed library has.

Template-decisions C2 (type first) and D9 (boundaries); guide §6 and §10.
"""

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from boundaries import declared_distributions, declared_import_names, import_names, stub_drift

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
# The code the gate reads, and so the first-party import names. A second adapter
# (cli_adapter/) is listed here too (template-decisions D2).
CODE = ("backend_logic", "http_adapter")
DYNAMIC = {"import_module", "__import__"}


@dataclass(frozen=True)
class DynamicImport:
    line: int
    name: str  # import_module or __import__


def line_of(found: DynamicImport) -> int:
    return found.line


def dynamic_imports(source: str) -> list[DynamicImport]:
    """Every reference to a loader by name: a call, an attribute read, an alias, an import.

    References are reported, not only calls, so `load = importlib.import_module` and
    `from importlib import import_module as load` are caught where the alias is made.
    """
    found: list[DynamicImport] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            found += [
                DynamicImport(node.lineno, alias.name)
                for alias in node.names
                if alias.name in DYNAMIC
            ]
        elif isinstance(node, ast.Attribute) and node.attr in DYNAMIC:
            found.append(DynamicImport(node.lineno, node.attr))
        elif isinstance(node, ast.Name) and node.id in DYNAMIC:
            found.append(DynamicImport(node.lineno, node.id))
    return sorted(found, key=line_of)


def third_party_imports(source: str, first_party: set[str]) -> list[tuple[int, str]]:
    """(line, module) of every absolute import outside the standard library and the project,
    at any depth: top level, `lazy`, inside a function or an `if TYPE_CHECKING` block."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules = [node.module]
        else:
            continue
        found += [
            (node.lineno, module)
            for module in modules
            if module.split(".")[0] not in sys.stdlib_module_names
            and module.split(".")[0] not in first_party
        ]
    return sorted(found)


def code_files() -> list[Path]:
    found = sorted(path for name in CODE for path in (ROOT / name).rglob("*.py"))
    # An empty scan would pass every rule by finding nothing to break.
    assert len(found) >= len(CODE), f"scanned only {len(found)} file(s): wrong tree"
    return found


def stub_module(stub: Path) -> str:
    parts = stub.relative_to(SUPPORT).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def test_dynamic_import_scanner_sees_every_form() -> None:
    # Guards the guard: a scanner for `importlib.import_module(` alone would miss the alias,
    # the builtin, the reference without a call and the import that renames it.
    source = (
        "import importlib\n"
        "from importlib import import_module as load\n"
        "lazy from importlib import import_module\n"
        "import builtins\n"
        "top = importlib.import_module('a')\n"
        "def f(name):\n"
        "    __import__('b')\n"
        "    loader = importlib.__import__\n"
        "    builtins.__import__('c')\n"
        "    return load(name)\n"
        "text = \"importlib.import_module('d')\"  # a string is not a call\n"
        "import importlib.metadata\n"
    )
    assert dynamic_imports(source) == [
        DynamicImport(2, "import_module"),
        DynamicImport(3, "import_module"),
        DynamicImport(5, "import_module"),
        DynamicImport(7, "__import__"),
        DynamicImport(8, "__import__"),
        DynamicImport(9, "__import__"),
    ]


def test_third_party_scanner_sees_every_import_form() -> None:
    # Guards the guard: `from x import y`, `lazy` imports and imports inside a function or a
    # TYPE_CHECKING block count; the standard library, relative and first-party imports do not.
    source = (
        "from __future__ import annotations\n"
        "import os.path\n"
        "lazy import fastapi\n"
        "lazy from fastapi.responses import JSONResponse\n"
        "from . import sibling\n"
        "from .contracts import Request\n"
        "from backend_logic.notes import run\n"
        "import http_adapter.application, yaml\n"
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from starlette.requests import Request\n"
        "def f():\n"
        "    import httpx\n"
    )
    assert third_party_imports(source, {"backend_logic", "http_adapter"}) == [
        (3, "fastapi"),
        (4, "fastapi.responses"),
        (8, "yaml"),
        (11, "starlette.requests"),
        (13, "httpx"),
    ]


def write_distribution(root: Path, name: str, top: str, *requires: str) -> None:
    info = root / f"{name.replace('-', '_')}-1.0.dist-info"
    info.mkdir()
    lines = [f"Metadata-Version: 2.1\nName: {name}\nVersion: 1.0\n"]
    lines += [f"Requires-Dist: {requirement}\n" for requirement in requires]
    (info / "METADATA").write_text("".join(lines), encoding="utf-8")
    (info / "top_level.txt").write_text(f"{top}\n", encoding="utf-8")


def test_dependency_reader_grants_only_what_is_declared(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Guards the reader with synthetic distributions, so it holds in any project: a
    # requested extra is granted (in either quote style, whatever the case of the name), and
    # so is an extra an extra requests; an absent requirement with a marker is skipped; a
    # transitive dependency is never granted; a declared distribution that is not installed
    # fails.
    write_distribution(
        tmp_path,
        "Pkg-Main",
        "pkgmain",
        "pkg-transitive>=1",
        'pkg_extra; extra == "full"',
        "pkg-absent; python_version >= '3' and extra == 'full'",
        "pkg-other; extra == 'other'",
    )
    write_distribution(tmp_path, "pkg-transitive", "pkgtransitive")
    write_distribution(tmp_path, "pkg-extra", "pkgextra")
    write_distribution(tmp_path, "pkg-other", "pkgother")
    write_distribution(tmp_path, "pkg-chain", "pkgchain", "pkg-main[full]; extra == 'all'")
    monkeypatch.syspath_prepend(str(tmp_path))
    assert declared_distributions(["pkg.main>=1.0"]) == {"pkg-main"}
    assert declared_distributions(["Pkg_Main[full] >= 1"]) == {"pkg-main", "pkg-extra"}
    assert declared_distributions(["pkg-chain[all]"]) == {"pkg-chain", "pkg-main", "pkg-extra"}
    assert declared_distributions(["pkg-nowhere; sys_platform == 'win32'"]) == set()
    assert import_names({"pkg-main", "pkg-extra"}) == {"pkgmain", "pkgextra"}
    with pytest.raises(LookupError):
        declared_distributions(["pkg-nowhere"])


def test_stub_checker_reports_every_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Guards the guard against a synthetic library: every kind of drift is reported, and what
    # matches (a None-valued attribute, a constructor attribute, a classmethod, a property and
    # its setter, an async method, a positional-only parameter, private typing helpers) is not.
    (tmp_path / "stub_target.py").write_text(
        "class Base(Exception): ...\n"
        "class Other: ...\n"
        "class Thing(Base):\n"
        "    flag = None\n"
        "    def __init__(self, name): self.name = name\n"
        "    def method(self, data, /, mode='r', *, check=False): ...\n"
        "    @classmethod\n"
        "    def make(cls, size): ...\n"
        "    @property\n"
        "    def size(self): return 1\n"
        "    @size.setter\n"
        "    def size(self, value): ...\n"
        "    async def fetch(self, key): ...\n"
        "async def gather(items): ...\n"
        "def function(text, /, *, strict=False): ...\n"
        "def needs(a, b): ...\n"
        "def short(a): ...\n"
        "CONSTANT = None\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    stub = (
        "from typing import Self, TypeVar\n"
        "_T = TypeVar('_T')\n"
        "type Alias = int\n"
        "class Missing: ...\n"
        "class Thing(Base):\n"
        "    flag: int | None\n"
        "    name: str\n"
        "    def method(self, data: bytes, /, mode: str = ..., *, check: bool = ...) -> None: ...\n"
        "    @classmethod\n"
        "    def make(cls, size: int) -> Self: ...\n"
        "    @property\n"
        "    def size(self) -> int: ...\n"
        "    @size.setter\n"
        "    def size(self, value: int) -> None: ...\n"
        "    async def fetch(self, key: str) -> None: ...\n"
        "async def gather(items: list[int]) -> None: ...\n"
        "def function(text: str, /, *, strict: bool = ...) -> None: ...\n"
        "CONSTANT: None\n"
        "class Bad(Other):\n"
        "    colour: str\n"
        "    def gone(self) -> None: ...\n"
        "    x = 1\n"
        "def absent() -> None: ...\n"
        "def function(text: str) -> None: ...\n"
        "def needs(a: int, c: int) -> None: ...\n"
        "def needs(a: int) -> None: ...\n"
        "def short(a: int, b: int = ..., *args: int) -> None: ...\n"
        "def short(a: int, *, force: bool) -> None: ...\n"
        "NOPE: int\n"
        "async def gone_async() -> None: ...\n"
        "PUBLIC = int\n"
        "if True: ...\n"
    )
    # A class missing in the library cannot be checked further; Bad is not in it either.
    assert stub_drift(stub, "stub_target") == [
        "stub_target.Missing: no such class in the library",
        "stub_target.Bad: no such class in the library",
        "stub_target.absent: no such function in the library",
        "stub_target.function: text is positional-only in the library",
        "stub_target.needs: positional 1 is b, not c",
        "stub_target.needs: a call with the stub's required parameters fails:"
        " missing a required argument: 'b'",
        "stub_target.short: takes no positional parameter b",
        "stub_target.short: takes no *args",
        "stub_target.short: takes no keyword parameter force",
        "stub_target.NOPE: no such name in the library",
        "stub_target.gone_async: no such function in the library",
        "stub_target: line 31 is not a class, function or annotation",
        "stub_target: line 32 is not a class, function or annotation",
    ]
    wrong_class = (
        "class Thing(Other):\n"
        "    colour: str\n"
        "    def gone(self) -> None: ...\n"
        "    def method(self, data: bytes, *, force: bool = ...) -> None: ...\n"
        "    x = 1\n"
    )
    assert stub_drift(wrong_class, "stub_target") == [
        "stub_target.Thing: does not derive from Other in the library",
        "stub_target.Thing.colour: no such attribute in the library",
        "stub_target.Thing.gone: no such method in the library",
        "stub_target.Thing.method: data is positional-only in the library",
        "stub_target.Thing.method: takes no keyword parameter force",
        "stub_target.Thing: line 5 is not a method or annotated attribute",
    ]
    assert stub_drift("", "no_such_module_for_the_stub_checker") == [
        "no_such_module_for_the_stub_checker: not installed"
    ]


def test_no_module_is_loaded_by_name() -> None:
    violations = [
        f"{path.relative_to(ROOT)}:{found.line} uses {found.name}: import the module plainly"
        for path in code_files()
        for found in dynamic_imports(path.read_text(encoding="utf-8"))
    ]
    assert not violations, "\n".join(violations)


def test_third_party_only_from_declared_dependencies() -> None:
    declared = declared_import_names(ROOT / "pyproject.toml")
    violations = [
        f"{path.relative_to(ROOT)}:{line} imports {module}: "
        f"{module.split('.')[0]} is not in [project] dependencies of pyproject.toml"
        for path in code_files()
        for line, module in third_party_imports(path.read_text(encoding="utf-8"), set(CODE))
        if module.split(".")[0] not in declared
    ]
    assert not violations, "\n".join(violations)


def test_every_stub_matches_the_installed_library() -> None:
    stubs = sorted(SUPPORT.rglob("*.pyi"))
    # tests/gates/test_config.py reads pyproject.toml through the template's tomllib.pyi.
    assert SUPPORT / "tomllib.pyi" in stubs
    drift = [
        line
        for stub in stubs
        for line in stub_drift(stub.read_text(encoding="utf-8"), stub_module(stub))
    ]
    assert not drift, "\n".join(drift)
