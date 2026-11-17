"""Readers for tests/gates/test_boundaries.py: declared dependencies and typed stubs.

- `declared_import_names(pyproject)`: the top-level import names that the `[project]
  dependencies` of a pyproject grant, extras included, resolved against the installed
  environment (the distributions' metadata is only there). No list of libraries is kept in the
  gates: declaring a dependency in pyproject.toml is what grants its import.
- `stub_drift(stub, module)`: what a typed stub (`.pyi`) declares that the installed module does
  not have. A stub replaces the library's own types for mypy, so a name or a parameter that
  the library dropped would type-check and fail only at run time.

Copied from the template and never edited in a project, like the gates that read it.
"""

import ast
import inspect
import pydoc
import re
import tomllib
from importlib import metadata
from pathlib import Path
from typing import Protocol, runtime_checkable

# PEP 508: the name at the start of a requirement, its extras, and the extras a marker names.
REQUIREMENT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
REQUIREMENT_EXTRAS = re.compile(r"\[([^\]]*)\]")
MARKER_EXTRA = re.compile(r"""extra\s*==\s*['"]([^'"]+)['"]""")

# inspect.Parameter's kinds by name: the class itself is typed with Any (its `default`).
POSITIONAL = {"POSITIONAL_ONLY", "POSITIONAL_OR_KEYWORD"}
KEYWORD = {"KEYWORD_ONLY", "POSITIONAL_OR_KEYWORD"}
# Decorators that make a stub method an attribute of the instance, not a call.
DESCRIPTORS = {"property", "cached_property", "setter", "getter", "deleter"}


@runtime_checkable
class Class(Protocol):
    """What a class has and an instance does not; isinstance(x, type) would carry Any."""

    __mro__: tuple[object, ...]


def normalized(name: str) -> str:
    """PEP 503: distribution names compare without case and `-`/`_`/`.` differences."""
    return re.sub(r"[-_.]+", "-", name).lower()


def first_group(match: re.Match[str]) -> str:
    """typeshed types a group as `str | Any`; the annotation takes the Any out."""
    text: str | None = match.group(1)
    return text or ""


def requirement_name(spec: str) -> str:
    match = REQUIREMENT_NAME.match(spec.strip())
    if match is None:
        raise ValueError(f"not a PEP 508 requirement: {spec!r}")
    return normalized(match.group(0))


def extras_of(spec: str) -> set[str]:
    match = REQUIREMENT_EXTRAS.search(spec.partition(";")[0])
    if match is None:
        return set()
    return {normalized(extra) for extra in first_group(match).split(",") if extra.strip()}


def installed(name: str) -> bool:
    try:
        metadata.distribution(name)
    except metadata.PackageNotFoundError:
        return False
    return True


def declared_distributions(specs: list[str]) -> set[str]:
    """The named distributions plus those their requested extras add, an extra that requests
    another extra included; never a transitive dependency.

    A requirement that is not installed and carries a marker is skipped: the marker excluded
    it on this platform (uvloop on Windows). A declared distribution without a marker that is
    not installed fails: the environment is not synced.
    """
    found: set[str] = set()
    pending = [(requirement_name(spec), extras_of(spec), ";" in spec) for spec in specs]
    visited: set[tuple[str, frozenset[str]]] = set()
    while pending:
        name, extras, marked = pending.pop()
        if (name, frozenset(extras)) in visited:
            continue
        visited.add((name, frozenset(extras)))
        if not installed(name):
            if marked:
                continue
            raise LookupError(f"{name} is declared but not installed: run `uv sync`")
        found.add(name)
        for requirement in metadata.distribution(name).requires or []:
            _, _, marker = requirement.partition(";")
            named = {normalized(first_group(match)) for match in MARKER_EXTRA.finditer(marker)}
            if extras & named:
                pending.append((requirement_name(requirement), extras_of(requirement), True))
    return found


def import_names(distributions: set[str]) -> set[str]:
    """Top-level import names the installed distributions provide (PyYAML provides yaml)."""
    return {
        top
        for top, providers in metadata.packages_distributions().items()
        if any(normalized(provider) in distributions for provider in providers)
    }


def declared_import_names(pyproject: Path) -> set[str]:
    document = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    project = document["project"]
    if not isinstance(project, dict):
        raise TypeError(f"{pyproject}: [project] must be a table")
    dependencies: object = project.get("dependencies", [])
    if not isinstance(dependencies, list):
        raise TypeError(f"{pyproject}: [project] dependencies must be a list")
    return import_names(declared_distributions([str(spec) for spec in dependencies]))


def exists(dotted: str) -> bool:
    """Whether the installed library has this dotted name (its value may be None)."""
    parent, _, name = dotted.rpartition(".")
    owner = pydoc.locate(parent)
    return owner is not None and hasattr(owner, name)


def located(dotted: str) -> object:
    """The installed object at a dotted path; pydoc.locate types it as object, never Any."""
    return pydoc.locate(dotted)


type Function = ast.FunctionDef | ast.AsyncFunctionDef


def decorator_names(function: Function) -> set[str]:
    """`property`, `x.setter`, `functools.cached_property`: the last name of each decorator."""
    names: set[str] = set()
    for node in function.decorator_list:
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    return names


def signature_drift(function: Function, real: object, where: str, *, in_class: bool) -> list[str]:
    """Each declared parameter must be accepted in the same way; and a call that passes only
    the stub's required parameters must bind, so the stub omits nothing the library needs.

    An attribute declared as a method (a property, its setter) and a callable whose signature
    the library does not expose (some C extensions) are checked only for existing.
    """
    decorators = decorator_names(function)
    if decorators & DESCRIPTORS:
        return []
    if not callable(real):
        return [f"{where}: is not callable in the library"]
    try:
        parameters = list(inspect.signature(real).parameters.values())
    except ValueError:
        return []
    args = function.args
    positional = [*args.posonlyargs, *args.args]
    if "classmethod" in decorators and positional:
        positional = positional[1:]  # located through the class, the method is already bound
    # An instance method's first parameter is self: always passed positionally, never by name.
    receiver = in_class and "classmethod" not in decorators and "staticmethod" not in decorators
    drift: list[str] = []
    real_positional = [parameter for parameter in parameters if parameter.kind.name in POSITIONAL]
    kinds = {parameter.kind.name for parameter in parameters}
    for index, argument in enumerate(positional):
        if index >= len(real_positional):
            if "VAR_POSITIONAL" not in kinds:
                drift.append(f"{where}: takes no positional parameter {argument.arg}")
            continue
        at_index = real_positional[index]
        if receiver and index == 0:
            continue
        if argument in args.args and at_index.name != argument.arg:
            drift.append(f"{where}: positional {index} is {at_index.name}, not {argument.arg}")
        elif argument in args.args and at_index.kind.name == "POSITIONAL_ONLY":
            drift.append(f"{where}: {argument.arg} is positional-only in the library")
    by_name = {parameter.name: parameter for parameter in parameters}
    for argument in args.kwonlyargs:
        named = by_name.get(argument.arg)
        accepted = named is not None and named.kind.name in KEYWORD
        if not accepted and "VAR_KEYWORD" not in kinds:
            drift.append(f"{where}: takes no keyword parameter {argument.arg}")
    if args.vararg is not None and "VAR_POSITIONAL" not in kinds:
        drift.append(f"{where}: takes no *{args.vararg.arg}")
    if args.kwarg is not None and "VAR_KEYWORD" not in kinds:
        drift.append(f"{where}: takes no **{args.kwarg.arg}")
    # Defaults align with the end of the positional list and one per keyword-only parameter.
    required_count = len(positional) - len(args.defaults)
    required_keywords = [
        argument.arg
        for argument, default in zip(args.kwonlyargs, args.kw_defaults, strict=True)
        if default is None
    ]
    if not drift:
        placeholders = [object()] * max(required_count, 0)
        keywords = {name: object() for name in required_keywords}
        try:
            inspect.signature(real).bind(*placeholders, **keywords)
        except TypeError as error:
            drift.append(f"{where}: a call with the stub's required parameters fails: {error}")
    return drift


def class_drift(node: ast.ClassDef, module: str) -> list[str]:
    where = f"{module}.{node.name}"
    real = located(where) if exists(where) else None
    if not isinstance(real, Class):
        return [f"{where}: no such class in the library"]
    drift: list[str] = []
    for base in node.bases:
        if not isinstance(base, ast.Name):
            drift.append(f"{where}: base {ast.unparse(base)} is not checked; name it plainly")
            continue
        local = f"{module}.{base.id}"
        expected = located(local if exists(local) else f"builtins.{base.id}")
        if not isinstance(expected, Class) or expected not in real.__mro__:
            drift.append(f"{where}: does not derive from {base.id} in the library")
    init = located(f"{where}.__init__")
    try:
        init_names = set(inspect.signature(init).parameters) if callable(init) else set()
    except ValueError:
        init_names = set()
    for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not exists(f"{where}.{item.name}"):
                drift.append(f"{where}.{item.name}: no such method in the library")
            else:
                method = located(f"{where}.{item.name}")
                drift += signature_drift(item, method, f"{where}.{item.name}", in_class=True)
        elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
            # A class attribute, a property, or an attribute the constructor sets by name.
            name = item.target.id
            if not exists(f"{where}.{name}") and name not in init_names:
                drift.append(f"{where}.{name}: no such attribute in the library")
        elif not is_inert(item) and not is_typing_only(item):
            drift.append(f"{where}: line {item.lineno} is not a method or annotated attribute")
    return drift


def is_typing_only(node: ast.stmt) -> bool:
    """`type X = ...` or an assignment to private names (`_T = TypeVar("_T")`): names the
    stub uses for its own annotations, which the library need not have."""
    if isinstance(node, ast.TypeAlias):
        return True
    return isinstance(node, ast.Assign) and all(
        isinstance(target, ast.Name) and target.id.startswith("_") for target in node.targets
    )


def is_inert(node: ast.stmt) -> bool:
    """`...`, a docstring or `pass`: statements that declare nothing."""
    if isinstance(node, ast.Pass):
        return True
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)


def stub_drift(stub: str, module: str) -> list[str]:
    """Every name, base, parameter and attribute the stub declares, against the installed module.

    Reads only top-level classes, functions, annotated names, imports and private typing
    helpers (`_T = TypeVar("_T")`, `type X = ...`); any other statement (an `if
    sys.version_info` branch, a public bare assignment) is reported, so nothing hides in it.
    """
    if pydoc.locate(module) is None:
        return [f"{module}: not installed"]
    drift: list[str] = []
    for node in ast.parse(stub).body:
        if isinstance(node, ast.ClassDef):
            drift += class_drift(node, module)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not exists(f"{module}.{node.name}"):
                drift.append(f"{module}.{node.name}: no such function in the library")
            else:
                real = located(f"{module}.{node.name}")
                drift += signature_drift(node, real, f"{module}.{node.name}", in_class=False)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if not exists(f"{module}.{node.target.id}"):
                drift.append(f"{module}.{node.target.id}: no such name in the library")
        elif isinstance(node, (ast.Import, ast.ImportFrom)) or is_inert(node):
            continue
        elif not is_typing_only(node):
            drift.append(f"{module}: line {node.lineno} is not a class, function or annotation")
    return drift
