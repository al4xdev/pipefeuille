"""Which libraries the code may use, how it loads them, and the stubs that type them.

- A third-party import in `backend_logic` or `http_adapter` names a library of the
  `[project] dependencies` of pyproject.toml, extras included (support/boundaries.py reads them
  from the installed metadata). A library that is only installed (a transitive dependency, a
  dev tool such as httpx) is not granted: declaring it is what grants the import.
- Nothing in that code can load a module by a string: it imports and uses none of LOADERS
  (modules with their submodules, and single objects), touches no `sys.modules`, and names
  none of the builtins that reach the import machinery or run a string (LOADER_NAMES).
  LOADERS is audited: every module in reach that calls the import machinery is in it or in
  NOT_A_LOADER, with its reason. Every library is a
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
from boundaries import (
    declared_distributions,
    declared_import_names,
    distribution_sources,
    import_names,
    loader_candidates,
    project_dependencies,
    stdlib_sources,
    stub_drift,
    tree_sources,
)

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
# The code the gate reads, and so the first-party import names. A second adapter
# (cli_adapter/) is listed here too (template-decisions D2).
CODE = ("backend_logic", "http_adapter")
# What loads a module, or runs code, from a string: a module (every submodule included) or one
# object of a module. Importing it, or using it through any name bound to it, is the violation.
# Closed and reviewed: test_every_loader_in_reach_is_listed fails when the standard library or
# a template dependency calls the import machinery in a module listed neither here nor in
# NOT_A_LOADER. A new entry is a change to the pipefeuille (RUNBOOK, task C), never a project's.
LOADERS = {
    "importlib": "the import machinery itself (util, machinery, metadata, resources)",
    "_frozen_importlib": "importlib's bootstrap, under its private name",
    "_frozen_importlib_external": "importlib's path finders, under their private name",
    "_imp": "the interpreter's import primitives",
    "pydoc": "pydoc.locate imports any dotted name",
    "runpy": "runs a module or a file by name",
    "pkgutil": "resolve_name, iter_modules + import, get_data by package name",
    "zipimport": "loads modules from an archive",
    "builtins": "builtins.__import__ and exec under an attribute",
    "modulefinder": "finds and loads modules by name",
    "doctest": "imports the module it tests by name",
    "unittest": "loads tests and patch targets (mock.patch) by dotted name",
    "logging.config": "dictConfig and fileConfig import the factories their data names",
    "pickle": "unpickling imports the module of every class the data names",
    "_pickle": "pickle's accelerator, the same unpickling",
    "shelve": "stores values with pickle",
    "multiprocessing.forkserver": "set_forkserver_preload imports the modules it is given",
    "multiprocessing.set_forkserver_preload": "the same, from the package",
    "optparse": "Values.read_module imports a module by name",
    "xml.dom.domreg": "getDOMImplementation imports the implementation it is given",
    "xml.dom.getDOMImplementation": "the same, from the package",
    "xml.sax.make_parser": "imports the parser modules its argument names",
    "turtle": "imports the modules its configuration names",
    "profiling": "profiles a module or a script by name",
    "profile": "runs a code string",
    "cProfile": "runs a code string",
    "timeit": "compiles and runs code strings",
    "trace": "runs a code string or a module",
    "pdb": "runs a code string or a module",
    "bdb": "runs a code string",
    "code": "an interpreter for code strings",
    "codeop": "compiles code strings for an interpreter",
    "uvicorn": "run, Config.load, Server and main import the app from a 'module:attr' string",
    "watchfiles.run": "run_process and arun_process import the target a string names",
    "watchfiles.run_process": "the same, from the package",
    "watchfiles.arun_process": "the same, from the package",
    "watchfiles.cli": "runs watchfiles.run on a target string",
    "websockets.imports": "lazy_import imports the names a mapping lists",
    "websockets.lazy_import": "the same, from the package",
    "yaml.constructor": "!!python/name and !!python/object tags import the modules they name",
    "yaml.loader": "Loader and UnsafeLoader use that constructor",
    "yaml.cyaml": "CLoader and CUnsafeLoader use that constructor",
    "yaml.Loader": "the unsafe constructor, from the package",
    "yaml.UnsafeLoader": "the unsafe constructor, from the package",
    "yaml.CLoader": "the unsafe constructor, from the package",
    "yaml.CUnsafeLoader": "the unsafe constructor, from the package",
    "yaml.unsafe_load": "the unsafe constructor, from the package",
    "yaml.unsafe_load_all": "the unsafe constructor, from the package",
}
# Modules in reach of the code that call the import machinery, but never on a name the caller or
# the data chooses: each with the reason it was reviewed and not listed in LOADERS.
NOT_A_LOADER = {
    "ctypes": "imports the fixed comtypes.server.inprocserver, for Windows COM only",
    "dbm": "imports one of its own backends, from a fixed list",
    "encodings": "imports encodings.<codec>: only modules of its own package",
    "inspect": "only its command line (_main, python -m inspect) imports by name",
    "sysconfig": "imports its own _sysconfigdata build module",
    "traceback": "imports the module an ImportError already names, to suggest a spelling",
    "xml.sax": "loads by name only in make_parser, which is in LOADERS",
    "fastapi.responses": "imports the optional ujson and orjson, fixed names",
    "dotenv.main": "imports __main__, a fixed name, to find the caller's directory",
}
# The distributions whose modules LOADERS and NOT_A_LOADER were reviewed against: the
# template's own dependencies. A project's added dependency is not audited (template-decisions
# D9, "Does not prove"): the tables live in this file, which a project never edits.
AUDITED_DISTRIBUTIONS = {
    "fastapi",
    "uvicorn",
    "httptools",
    "python-dotenv",
    "pyyaml",
    "watchfiles",
    "websockets",
}
# Builtins that reach the import machinery or run a string, available without any import.
LOADER_NAMES = {"__import__", "__builtins__", "__loader__", "__spec__", "exec", "eval"}
# Loader functions and methods reached as an attribute of something the scanner cannot
# resolve (an object, a parameter): their names are reserved in the code.
LOADER_ATTRIBUTES = {
    "__import__",
    "import_module",
    "import_from_string",
    "import_string",
    "lazy_import",
    "find_spec",
    "module_from_spec",
    "spec_from_file_location",
    "spec_from_loader",
    "exec_module",
    "load_module",
    "read_module",
    "set_forkserver_preload",
    "find_class",
}


@dataclass(frozen=True, order=True)
class LoaderUse:
    line: int
    what: str  # the LOADERS entry, `sys.modules`, or the builtin or attribute name


def dotted(node: ast.expr, bindings: dict[str, set[str]]) -> set[str]:
    """Every dotted name `n.a.b` can stand for, given every value each name was bound to."""
    parts: list[str] = []
    while isinstance(node, (ast.Attribute, ast.NamedExpr)):
        if isinstance(node, ast.Attribute):
            parts.append(node.attr)
        node = node.value  # `(x := yaml).load` stands for `yaml.load`
    if not isinstance(node, ast.Name):
        return set()
    suffix = "".join(f".{part}" for part in reversed(parts))
    return {f"{bound}{suffix}" for bound in bindings.get(node.id, set())}


def loader_of(name: str) -> str | None:
    """The LOADERS entry a dotted name is, or lies under; `sys.modules` at any depth."""
    for path in LOADERS:
        if name == path or name.startswith(f"{path}."):
            return path
    parts = name.split(".")
    if any(pair == ("sys", "modules") for pair in zip(parts, parts[1:], strict=False)):
        return "sys.modules"
    return None


def bound_names(tree: ast.Module) -> dict[str, set[str]]:
    """Every dotted value each name was ever bound to, never only the last: imports, then
    `x = y`, `x: T = y`, `(x := y)` and parameter defaults (`def f(m=sys)`) propagated to a
    fixed point. A name rebound later keeps its earlier bindings, so shadowing hides nothing."""
    bindings: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name if alias.asname else alias.name.split(".")[0]
                bindings.setdefault(alias.asname or name, set()).add(name)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            for alias in node.names:
                full = f"{node.module}.{alias.name}"
                bindings.setdefault(alias.asname or alias.name, set()).add(full)
    pairs: list[tuple[str, ast.expr]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            pairs += [(t.id, node.value) for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)) and node.value is not None:
            if isinstance(node.target, ast.Name):
                pairs.append((node.target.id, node.value))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            arguments = node.args
            positional = [*arguments.posonlyargs, *arguments.args]
            with_defaults = positional[len(positional) - len(arguments.defaults) :]
            pairs += [(a.arg, d) for a, d in zip(with_defaults, arguments.defaults, strict=True)]
            pairs += [
                (a.arg, d)
                for a, d in zip(arguments.kwonlyargs, arguments.kw_defaults, strict=True)
                if d is not None
            ]
    changed = True
    while changed:
        changed = False
        for name, value in pairs:
            values = dotted(value, bindings)
            if not values <= bindings.get(name, set()):
                bindings.setdefault(name, set()).update(values)
                changed = True
    return bindings


def loader_uses(source: str) -> list[LoaderUse]:
    """Every import of a LOADERS entry, every use of a name that was ever bound to one, every
    `sys.modules`, and every loader builtin or attribute name, at any depth."""
    tree = ast.parse(source)
    bindings = bound_names(tree)
    found: set[LoaderUse] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {
                LoaderUse(node.lineno, path)
                for alias in node.names
                if (path := loader_of(alias.name)) is not None
            }
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found |= {
                LoaderUse(node.lineno, path)
                for alias in node.names
                if (path := loader_of(node.module) or loader_of(f"{node.module}.{alias.name}"))
                is not None
            }
        elif isinstance(node, ast.Name) and node.id in LOADER_NAMES:
            found.add(LoaderUse(node.lineno, node.id))
        if isinstance(node, (ast.Name, ast.Attribute)) and isinstance(node.ctx, ast.Load):
            names = dotted(node, bindings)
            found |= {
                LoaderUse(node.lineno, path)
                for name in names
                if (path := loader_of(name)) is not None
            }
            if not names and isinstance(node, ast.Attribute) and node.attr in LOADER_ATTRIBUTES:
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
    # Guards the guard: each flagged line is a way to load a module by a string; the last line
    # holds uses that are not one (sys.argv, os.path, yaml.safe_load, an object's own exec or
    # modules). Line 14 rebinds `sys`: the earlier binding still counts on lines 19-24, through
    # an assignment (21), a walrus (23) and a parameter default (15, 24).
    source = (
        "import importlib\n"
        "from importlib import import_module as load\n"
        "lazy from importlib.util import find_spec, module_from_spec\n"
        "import pydoc, runpy as r\n"
        "import uvicorn\n"
        "import sys\n"
        "from sys import modules\n"
        "import os\n"
        "import yaml\n"
        "import websockets\n"
        "from watchfiles import run_process\n"
        "import _frozen_importlib\n"
        "import multiprocessing as mp\n"
        "from http_adapter import application as sys\n"
        "def f(name, holder, m=sys):\n"
        "    getattr(importlib, 'import_module')(name)\n"
        "    pydoc.locate('httpx.AsyncClient')\n"
        "    uvicorn.Config(app='pkg:attr').load()\n"
        "    sys.modules['starlette.requests']\n"
        "    os.sys.modules\n"
        "    runtime = sys\n"
        "    runtime.modules\n"
        "    (alias := yaml).unsafe_load(name)\n"
        "    m.modules\n"
        "    websockets.lazy_import(globals(), {})\n"
        "    run_process('.', target='pkg.main')\n"
        "    mp.set_forkserver_preload([name])\n"
        "    holder.read_module(name)\n"
        "    __import__('b')\n"
        "    exec('import httpx')\n"
        "    r.run_module(name)\n"
        "text = \"importlib.import_module('d')\"\n"
        "print(sys.argv, os.path.sep, yaml.safe_load(text), websockets.connect,"
        " holder.exec(), holder.modules)\n"
    )
    assert loader_uses(source) == [
        LoaderUse(1, "importlib"),
        LoaderUse(2, "importlib"),
        LoaderUse(3, "importlib"),
        LoaderUse(4, "pydoc"),
        LoaderUse(4, "runpy"),
        LoaderUse(5, "uvicorn"),
        LoaderUse(7, "sys.modules"),
        LoaderUse(11, "watchfiles.run_process"),
        LoaderUse(12, "_frozen_importlib"),
        LoaderUse(16, "importlib"),
        LoaderUse(17, "pydoc"),
        LoaderUse(18, "uvicorn"),
        LoaderUse(19, "sys.modules"),
        LoaderUse(20, "sys.modules"),
        LoaderUse(22, "sys.modules"),
        LoaderUse(23, "yaml.unsafe_load"),
        LoaderUse(24, "sys.modules"),
        LoaderUse(25, "websockets.lazy_import"),
        LoaderUse(26, "watchfiles.run_process"),
        LoaderUse(27, "multiprocessing.set_forkserver_preload"),
        LoaderUse(28, "read_module"),
        LoaderUse(29, "__import__"),
        LoaderUse(30, "exec"),
        LoaderUse(31, "runpy"),
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
    # __all__ in every form: whatever it lists is public, a plain import included.
    every_all = (
        "from httpx import AsyncClient\n"
        "__all__: list[str] = ['Thing', 'AsyncClient']\n"
        "__all__ += ['ghost_plus']\n"
        "__all__.extend(['ghost_extend'])\n"
        "__all__.append('ghost_append')\n"
        "__all__.remove('Thing')\n"
        "__all__ = [name for name in dir()]\n"
    )
    assert stub_drift(every_all, "stub_target") == [
        "stub_target.AsyncClient: listed in __all__, not in the library",
        "stub_target.ghost_plus: listed in __all__, not in the library",
        "stub_target.ghost_extend: listed in __all__, not in the library",
        "stub_target.ghost_append: listed in __all__, not in the library",
        "stub_target: line 6 sets __all__ in a form not read",
        "stub_target: line 7 sets __all__ in a form not read",
    ]
    # A default on one side only: the library's (ordered: b=1, c=2) or the stub's (needs).
    defaults = (
        "def ordered(a: int, b: int, *, c: int) -> None: ...\n"
        "def needs(a: int, b: int = ...) -> None: ...\n"
    )
    assert stub_drift(defaults, "stub_target") == [
        "stub_target.ordered: b has a default in the library, not in the stub",
        "stub_target.ordered: c has a default in the library, not in the stub",
        "stub_target.needs: b has a default in the stub, not in the library",
    ]
    assert stub_drift("", "no_such_module_for_the_stub_checker") == [
        "no_such_module_for_the_stub_checker: not installed"
    ]


def test_loader_audit_finds_every_caller_of_the_import_machinery(tmp_path: Path) -> None:
    # Guards the audit: a module is a candidate when its own source calls the import machinery
    # in any form; private modules, private packages and non-library folders are skipped, and a
    # name in a string or a comment is not a call.
    files = {
        "lib/clean.py": "import os\nos.getcwd()\n",
        "lib/loads.py": "import importlib\nimportlib.import_module(name)\n",
        "lib/builtin.py": "def f(n):\n    return __import__(n)\n",
        "lib/spec.py": "from importlib import util\nutil.find_spec(n)\n",
        "lib/exec.py": "spec.loader.exec_module(module)\n",
        "lib/sub/__init__.py": "m = load_module(n)\n",
        "lib/text.py": "doc = 'importlib.import_module(x)'  # import_module(y)\n",
        "lib/_private.py": "__import__(n)\n",
        "lib/_hidden/inner.py": "__import__(n)\n",
        "test/case.py": "__import__(n)\n",
    }
    for relative, text in files.items():
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / relative).write_text(text, encoding="utf-8")
    sources = tree_sources(tmp_path)
    assert [module for module, _ in sources] == [
        "lib.builtin",
        "lib.clean",
        "lib.exec",
        "lib.loads",
        "lib.spec",
        "lib.sub",
        "lib.text",
    ]
    assert loader_candidates(sources) == [
        "lib.builtin",
        "lib.exec",
        "lib.loads",
        "lib.spec",
        "lib.sub",
    ]


def test_every_loader_in_reach_is_listed() -> None:
    # A dependency upgrade or a Python upgrade that brings a new loader into reach of the code
    # turns this red until the pipefeuille reviews it into LOADERS or NOT_A_LOADER.
    audited = (
        declared_distributions(project_dependencies(ROOT / "pyproject.toml"))
        & AUDITED_DISTRIBUTIONS
    )
    candidates = loader_candidates(stdlib_sources() + distribution_sources(audited))
    # An empty audit would pass by reading nothing; the template's tree has 31 candidates.
    assert len(candidates) >= 20, f"the audit read only {len(candidates)} candidate(s)"
    unlisted = [
        module for module in candidates if loader_of(module) is None and module not in NOT_A_LOADER
    ]
    assert not unlisted, (
        "calls the import machinery and is reviewed in neither LOADERS nor NOT_A_LOADER of"
        f" tests/gates/test_boundaries.py (template-decisions D9): {unlisted}"
    )


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
