"""Which libraries the code may use, how it loads them, and the stubs that type them.

- A third-party import in `backend_logic` or `http_adapter` names a library of the
  `[project] dependencies` of pyproject.toml, extras included (support/boundaries.py reads them
  from the installed metadata). A library that is only installed (a transitive dependency, a
  dev tool such as httpx) is not granted: declaring it is what grants the import.
- Nothing in that code can load a module by a string: it imports none of the loader modules
  (LOADER_MODULES, submodules included), touches no `sys.modules`, and names none of the
  builtins that reach the import machinery or run a string (LOADER_NAMES). Every library is a
  plain import that mypy sees, typed by the library or by a stub. A module loaded by string
  hides a rename from the checker and its Any from disallow_any_expr, so there is no allowlist
  and no log token for it. The modules are forbidden, not their call names, because a call
  name is dodged by an alias, a `getattr` or a library's own helper.
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
# Modules that load code from a string: importing any of them, or a submodule, is the
# violation. `uvicorn.importer` is the declared server's own `import_from_string`; another
# declared library with such a helper is added here by the pipefeuille (RUNBOOK, task C).
LOADER_MODULES = (
    "importlib",
    "pydoc",
    "runpy",
    "pkgutil",
    "zipimport",
    "builtins",
    "uvicorn.importer",
)
# Builtins that reach the import machinery or run a string, available without any import.
LOADER_NAMES = {"__import__", "__builtins__", "__loader__", "__spec__", "exec", "eval"}
# Loader functions reached as an attribute of something the scanner cannot resolve.
LOADER_ATTRIBUTES = {"__import__", "import_module", "import_from_string"}


@dataclass(frozen=True, order=True)
class LoaderUse:
    line: int
    what: str  # the loader module, `sys.modules`, or the builtin or attribute name


def dotted(node: ast.expr, aliases: dict[str, str]) -> str | None:
    """`u.importer.x` as `uvicorn.importer.x` when `u` is bound by an import; else None."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name) or node.id not in aliases:
        return None
    return ".".join([aliases[node.id], *reversed(parts)])


def loader_of(name: str) -> str | None:
    """The loader module a dotted name is, or lies under; `sys.modules` at any depth."""
    for module in LOADER_MODULES:
        if name == module or name.startswith(f"{module}."):
            return module
    parts = name.split(".")
    if any(pair == ("sys", "modules") for pair in zip(parts, parts[1:], strict=False)):
        return "sys.modules"
    return None


def loader_uses(source: str) -> list[LoaderUse]:
    """Every import of a loader module, every use of a name bound to one (resolved through
    import aliases), every `sys.modules`, and every loader builtin, at any depth."""
    tree = ast.parse(source)
    aliases: dict[str, str] = {}
    found: set[LoaderUse] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                aliases[alias.asname or alias.name.split(".")[0]] = (
                    alias.name if alias.asname else alias.name.split(".")[0]
                )
                if (module := loader_of(alias.name)) is not None:
                    found.add(LoaderUse(node.lineno, module))
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            for alias in node.names:
                full = f"{node.module}.{alias.name}"
                aliases[alias.asname or alias.name] = full
                if (module := loader_of(node.module) or loader_of(full)) is not None:
                    found.add(LoaderUse(node.lineno, module))
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in LOADER_NAMES:
            found.add(LoaderUse(node.lineno, node.id))
        elif isinstance(node, (ast.Name, ast.Attribute)) and isinstance(node.ctx, ast.Load):
            name = dotted(node, aliases)
            module = loader_of(name) if name is not None else None
            if module is not None:
                found.add(LoaderUse(node.lineno, module))
            elif (
                name is None and isinstance(node, ast.Attribute) and node.attr in LOADER_ATTRIBUTES
            ):
                found.add(LoaderUse(node.lineno, node.attr))
    return sorted(found)


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


def test_loader_scanner_sees_every_form() -> None:
    # Guards the guard: each line is a way to load a module by a string. A scanner for
    # `importlib.import_module(` alone saw two of them.
    source = (
        "import importlib\n"
        "from importlib import import_module as load\n"
        "lazy from importlib.util import find_spec, module_from_spec\n"
        "import pydoc, runpy as r\n"
        "import uvicorn\n"
        "from uvicorn import importer\n"
        "import sys\n"
        "from sys import modules\n"
        "import os\n"
        "def f(name, holder):\n"
        "    getattr(importlib, 'import_module')(name)\n"
        "    pydoc.locate('httpx.AsyncClient')\n"
        "    uvicorn.importer.import_from_string('starlette.requests:Request')\n"
        "    sys.modules['starlette.requests']\n"
        "    os.sys.modules\n"
        "    __import__('b')\n"
        "    __builtins__\n"
        "    exec('import httpx')\n"
        "    eval(name)\n"
        "    holder.import_module(name)\n"
        "    r.run_module(name)\n"
        "text = \"importlib.import_module('d')\"  # a string is not a use\n"
        "print(sys.argv, os.path.sep, holder_modules := 1)\n"
    )
    assert loader_uses(source) == [
        LoaderUse(1, "importlib"),
        LoaderUse(2, "importlib"),
        LoaderUse(3, "importlib"),
        LoaderUse(4, "pydoc"),
        LoaderUse(4, "runpy"),
        LoaderUse(6, "uvicorn.importer"),
        LoaderUse(8, "sys.modules"),
        LoaderUse(11, "importlib"),
        LoaderUse(12, "pydoc"),
        LoaderUse(13, "uvicorn.importer"),
        LoaderUse(14, "sys.modules"),
        LoaderUse(15, "sys.modules"),
        LoaderUse(16, "__import__"),
        LoaderUse(17, "__builtins__"),
        LoaderUse(18, "exec"),
        LoaderUse(19, "eval"),
        LoaderUse(20, "import_module"),
        LoaderUse(21, "runpy"),
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
    # so is an extra an extra requests; an extra's requirement with a compound marker is never
    # granted, even when installed (no marker is guessed); an absent requirement with a marker
    # is skipped; a transitive dependency is never granted; a declared distribution that is not
    # installed fails.
    write_distribution(
        tmp_path,
        "Pkg-Main",
        "pkgmain",
        "pkg-transitive>=1",
        'pkg_extra; extra == "full"',
        "pkg-absent; python_version >= '3' and extra == 'full'",
        "pkg-other; extra == 'other'",
        'pkg-bad; extra == "full" and sys_platform == "never"',
        "pkg-either; extra == 'full' or extra == 'other'",
    )
    write_distribution(tmp_path, "pkg-transitive", "pkgtransitive")
    write_distribution(tmp_path, "pkg-extra", "pkgextra")
    write_distribution(tmp_path, "pkg-other", "pkgother")
    write_distribution(tmp_path, "pkg-bad", "pkgbad")
    write_distribution(tmp_path, "pkg-either", "pkgeither")
    write_distribution(tmp_path, "pkg-chain", "pkgchain", "pkg-main[full]; extra == 'all'")
    monkeypatch.syspath_prepend(str(tmp_path))
    assert declared_distributions(["pkg.main>=1.0"]) == {"pkg-main"}
    assert declared_distributions(["Pkg_Main[full] >= 1"]) == {"pkg-main", "pkg-extra"}
    assert declared_distributions(["pkg-chain[all]"]) == {"pkg-chain", "pkg-main", "pkg-extra"}
    assert declared_distributions(["pkg-nowhere; sys_platform == 'win32'"]) == set()
    assert import_names({"pkg-main", "pkg-extra"}) == {"pkgmain", "pkgextra"}
    with pytest.raises(LookupError):
        declared_distributions(["pkg-nowhere"])


LIBRARY = """
import os
class Base(Exception): ...
class Other: ...
class Thing(Base):
    flag = None
    def __init__(self, name): self.name = name
    def method(self, data, /, mode='r', *, check=False): ...
    @classmethod
    def make(cls, size): ...
    @property
    def size(self): return 1
    @size.setter
    def size(self, value): ...
    @property
    def fixed(self): return 1
    def plain(self): ...
    async def fetch(self, key): ...
async def gather(items): ...
def function(text, /, *, strict=False): ...
def needs(a, b): ...
def short(a): ...
def ordered(a, b=1, *, c=2): ...
def loose(a, **kwargs): ...
def load(fp): ...
CONSTANT = None
TEXT = 'x'
"""

MATCHING_STUB = """
from typing import Self, TypeVar
import os as os
_T = TypeVar("_T")
type _Alias = int
__all__ = ["Thing", "function"]
class Thing(Base):
    flag: int | None
    name: str
    def method(self, data: bytes, /, mode: str = ..., *, check: bool = ...) -> None: ...
    @classmethod
    def make(cls, size: int) -> Self: ...
    @property
    def size(self) -> int: ...
    @size.setter
    def size(self, value: int) -> None: ...
    @property
    def fixed(self) -> int: ...
    async def fetch(self, key: str) -> None: ...
async def gather(items: list[int]) -> None: ...
def function(text: str, /, *, strict: bool = ...) -> None: ...
def ordered(a: int) -> None: ...
def ordered(a: int, b: int = ..., *, c: int = ...) -> None: ...
CONSTANT: None
TEXT: str
"""

DRIFTING_STUB = """
from typing import Callable
from os import sep as sep
import json as json
from httpx import AsyncClient as AsyncClient
from os import *
__all__ = ["Thing", "ghost"]
class Missing: ...
def absent() -> None: ...
def function(text: str) -> None: ...
def needs(a: int, c: int) -> None: ...
def needs(a: int) -> None: ...
def needs(a: int, /, b: int) -> None: ...
def short(a: int, b: int = ..., *args: int) -> None: ...
def ordered(a: int, *, b: int = ...) -> None: ...
def ordered(a: int, c: int = ...) -> None: ...
def loose(a: int, *, invented: bool = ...) -> None: ...
load: Callable[[str], object]
TEXT: Callable[[], str]
NOPE: int
type Public = int
PUBLIC = int
_helper = 1
if True: ...
"""

DRIFTING_CLASS = """
from typing import Callable
class Thing(Other):
    colour: str
    def gone(self) -> None: ...
    def method(self, data: bytes, *, force: bool = ...) -> None: ...
    @property
    def plain(self) -> int: ...
    @fixed.setter
    def fixed(self, value: int) -> None: ...
    @property
    def phantom(self) -> int: ...
    fetch: Callable[[str], None]
    x = 1
"""


def test_stub_checker_reports_every_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Guards the guard against a synthetic library (LIBRARY): what matches is not reported
    # (a None-valued attribute, a constructor attribute, a classmethod, a property and its
    # setter, an async method, positional-only parameters, optional parameters left out, a
    # re-exported module, private typing helpers), and every kind of drift is, each once.
    (tmp_path / "stub_target.py").write_text(LIBRARY, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    assert stub_drift(MATCHING_STUB, "stub_target") == []
    assert stub_drift(DRIFTING_STUB, "stub_target") == [
        "stub_target.sep: re-exported by the stub, not in the library",
        "stub_target.json: re-exported by the stub, not in the library",
        "stub_target.AsyncClient: re-exported by the stub, not in the library",
        "stub_target: line 6 re-exports with *; name each import",
        "stub_target.ghost: listed in __all__, not in the library",
        "stub_target.Missing: no such class in the library",
        "stub_target.absent: no such function in the library",
        "stub_target.function: parameter 0 is positional-only text, not positional-or-keyword text",
        "stub_target.needs: parameter 1 is positional-or-keyword b, not positional-or-keyword c",
        "stub_target.needs: a call with the stub's required parameters fails:"
        " missing a required argument: 'b'",
        "stub_target.needs: parameter 0 is positional-or-keyword a, not positional-only a",
        "stub_target.short: takes no positional parameter b",
        "stub_target.short: takes no *args",
        "stub_target.ordered: b is positional-or-keyword, not keyword-only",
        "stub_target.ordered: parameter 1 is positional-or-keyword b, not positional-or-keyword c",
        "stub_target.loose: takes no keyword-only parameter invented",
        "stub_target.load: is a function in the library; declare it with def",
        "stub_target.TEXT: is not callable in the library",
        "stub_target.NOPE: no such name in the library",
        "stub_target: line 21 is not a class, function or annotation",
        "stub_target: line 22 is not a class, function or annotation",
        "stub_target: line 23 is not a class, function or annotation",
        "stub_target: line 24 is not a class, function or annotation",
    ]
    assert stub_drift(DRIFTING_CLASS, "stub_target") == [
        "stub_target.Thing: does not derive from Other in the library",
        "stub_target.Thing.colour: no such attribute in the library",
        "stub_target.Thing.gone: no such method in the library",
        "stub_target.Thing.method: parameter 1 is positional-only data,"
        " not positional-or-keyword data",
        "stub_target.Thing.method: takes no keyword-only parameter force",
        "stub_target.Thing.plain: is a method in the library, not a property",
        "stub_target.Thing.fixed: is read-only in the library",
        "stub_target.Thing.phantom: no such attribute in the library",
        "stub_target.Thing.fetch: is a function in the library; declare it with def",
        "stub_target.Thing: line 14 is not a method or annotated attribute",
    ]
    assert stub_drift("", "no_such_module_for_the_stub_checker") == [
        "no_such_module_for_the_stub_checker: not installed"
    ]


def test_no_module_is_loaded_by_name() -> None:
    violations = [
        f"{path.relative_to(ROOT)}:{found.line} uses {found.what}: import the module plainly"
        f" (template-decisions D9)"
        for path in code_files()
        for found in loader_uses(path.read_text(encoding="utf-8"))
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
