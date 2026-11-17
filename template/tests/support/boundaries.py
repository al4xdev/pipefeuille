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
# The only marker an extra's requirement may carry to be granted. Without a full marker
# evaluator in the standard library, a compound marker (`extra == "a" and sys_platform ==
# ...`) is refused rather than guessed: declare that library directly instead.
EXACT_EXTRA = re.compile(r"""\s*extra\s*==\s*['"]([^'"]+)['"]\s*""")

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

    An extra's requirement is granted only when its marker is exactly `extra == "<name>"` of
    a requested extra; a compound marker grants nothing (EXACT_EXTRA). A declared requirement
    with a marker that is not installed is skipped (its marker excluded it on this platform);
    one without a marker that is not installed fails: the environment is not synced.
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
            exact = EXACT_EXTRA.fullmatch(marker)
            if exact is not None and normalized(first_group(exact)) in extras:
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

KIND = {
    "POSITIONAL_ONLY": "positional-only",
    "POSITIONAL_OR_KEYWORD": "positional-or-keyword",
    "KEYWORD_ONLY": "keyword-only",
    "VAR_POSITIONAL": "*args",
    "VAR_KEYWORD": "**kwargs",
}
NOT_A_PROPERTY = object()
# Calls whose result is a name only the stub's annotations use (`_T = TypeVar("_T")`).
TYPE_HELPERS = {"TypeVar", "ParamSpec", "TypeVarTuple"}


def decorator_names(function: Function) -> set[str]:
    """`property`, `x.setter`, `functools.cached_property`: the last name of each decorator."""
    names: set[str] = set()
    for node in function.decorator_list:
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    return names


def mentions_callable(annotation: ast.expr) -> bool:
    return any(
        (isinstance(node, ast.Name) and node.id == "Callable")
        or (isinstance(node, ast.Attribute) and node.attr == "Callable")
        for node in ast.walk(annotation)
    )


def signature_drift(function: Function, real: object, where: str, *, in_class: bool) -> list[str]:
    """Every parameter the stub declares has the library's name, kind and position.

    The stub may leave out a parameter only if it has a default in the library, and a
    positional one only from the end (the binding check below catches a required one left
    out). A keyword the stub declares must be named in the library's signature even when the
    library also takes `**kwargs`. A callable whose signature the library does not expose
    (some C extensions) is checked only for existing.
    """
    decorators = decorator_names(function)
    if not callable(real):
        return [f"{where}: is not callable in the library"]
    try:
        parameters = list(inspect.signature(real).parameters.values())
    except ValueError:
        return []
    args = function.args
    declared = [(argument.arg, "POSITIONAL_ONLY") for argument in args.posonlyargs]
    declared += [(argument.arg, "POSITIONAL_OR_KEYWORD") for argument in args.args]
    defaults = len(args.defaults)
    if "classmethod" in decorators and declared:
        declared = declared[1:]  # located through the class, the method is already bound
    required_count = len(declared) - defaults
    real_positional = [parameter for parameter in parameters if parameter.kind.name in POSITIONAL]
    compared = list(enumerate(declared))
    if in_class and not decorators & {"classmethod", "staticmethod"} and compared:
        compared = compared[1:]  # self: always passed positionally, whatever its name
    drift: list[str] = []
    for index, (name, kind) in compared:
        if index >= len(real_positional):
            drift.append(f"{where}: takes no positional parameter {name}")
            continue
        real_parameter = real_positional[index]
        if (real_parameter.name, real_parameter.kind.name) != (name, kind):
            drift.append(
                f"{where}: parameter {index} is {KIND[real_parameter.kind.name]} "
                f"{real_parameter.name}, not {KIND[kind]} {name}"
            )
    by_name = {parameter.name: parameter for parameter in parameters}
    for argument in args.kwonlyargs:
        named = by_name.get(argument.arg)
        if named is None:
            drift.append(f"{where}: takes no keyword-only parameter {argument.arg}")
        elif named.kind.name != "KEYWORD_ONLY":
            drift.append(f"{where}: {argument.arg} is {KIND[named.kind.name]}, not keyword-only")
    kinds = {parameter.kind.name for parameter in parameters}
    if args.vararg is not None and "VAR_POSITIONAL" not in kinds:
        drift.append(f"{where}: takes no *{args.vararg.arg}")
    if args.kwarg is not None and "VAR_KEYWORD" not in kinds:
        drift.append(f"{where}: takes no **{args.kwarg.arg}")
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


def descriptor_drift(
    function: Function, owner: Class, where: str, init_names: set[str]
) -> list[str]:
    """A stub property is an attribute in the library, not a method; a stub setter needs one."""
    try:
        # The raw class attribute, unbound: a plain method stays a function here.
        raw: object = inspect.getattr_static(owner, function.name)
    except AttributeError:
        if function.name in init_names:
            return []  # an instance attribute the constructor sets: read-only in the stub
        return [f"{where}: no such attribute in the library"]
    if callable(raw):
        return [f"{where}: is a method in the library, not a property"]
    if "setter" in decorator_names(function):
        # A property has `fset`, None when read-only; isinstance(raw, property) would carry Any.
        # Other data descriptors (C getset descriptors) cannot say, and are accepted.
        setter: object = getattr(raw, "fset", NOT_A_PROPERTY)
        if setter is None:
            return [f"{where}: is read-only in the library"]
    return []


def attribute_drift(item: ast.AnnAssign, real: object, where: str) -> list[str]:
    """An annotated name the library has: a function is declared with `def` (so its signature
    is checked), and a `Callable` annotation needs something callable."""
    if callable(real) and not isinstance(real, Class):
        return [f"{where}: is a function in the library; declare it with def"]
    if not callable(real) and mentions_callable(item.annotation):
        return [f"{where}: is not callable in the library"]
    return []


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
            name = f"{where}.{item.name}"
            if decorator_names(item) & DESCRIPTORS:
                drift += descriptor_drift(item, real, name, init_names)
            elif not exists(name):
                drift.append(f"{name}: no such method in the library")
            else:
                drift += signature_drift(item, located(name), name, in_class=True)
        elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
            # A class attribute, a property, or an attribute the constructor sets by name.
            name = f"{where}.{item.target.id}"
            try:
                raw: object = inspect.getattr_static(real, item.target.id)
            except AttributeError:
                if item.target.id not in init_names:
                    drift.append(f"{name}: no such attribute in the library")
                continue
            drift += attribute_drift(item, raw, name)
        elif not is_inert(item) and not is_typing_only(item):
            drift.append(f"{where}: line {item.lineno} is not a method or annotated attribute")
    return drift


def is_typing_only(node: ast.stmt) -> bool:
    """A private name only the stub's annotations use: `type _X = ...` or `_T = TypeVar(...)`.
    Being private, the library need not have it; a public one is checked like any name."""
    if isinstance(node, ast.TypeAlias):
        return node.name.id.startswith("_")
    if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
        return False
    helper = node.value.func
    return (
        isinstance(helper, ast.Name)
        and helper.id in TYPE_HELPERS
        and all(
            isinstance(target, ast.Name)
            and target.id.startswith("_")
            and not target.id.startswith("__")
            for target in node.targets
        )
    )


def is_inert(node: ast.stmt) -> bool:
    """`...`, a docstring or `pass`: statements that declare nothing."""
    if isinstance(node, ast.Pass):
        return True
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)


def exported_names(node: ast.stmt) -> list[str] | None:
    """The names a stub statement re-exports, or None if it exports nothing.

    In a stub, an import is private unless written `import x as x` / `from y import a as a`;
    `__all__` exports what it lists (PEP 484). Those names must exist in the library.
    """
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names if alias.asname == alias.name]
    if isinstance(node, ast.ImportFrom):
        return [alias.name for alias in node.names if alias.asname == alias.name]
    return None


def all_names(node: ast.Assign) -> list[str] | None:
    """The literal strings of `__all__ = [...]`, or None when it is not a literal list."""
    if not isinstance(node.value, (ast.List, ast.Tuple)):
        return None
    names = [item.value for item in node.value.elts if isinstance(item, ast.Constant)]
    strings = [name for name in names if isinstance(name, str)]
    return strings if len(strings) == len(node.value.elts) else None


def stub_drift(stub: str, module: str) -> list[str]:
    """Every name, base, parameter, attribute and re-export the stub declares, against the
    installed module.

    Reads only top-level classes, functions, annotated names, imports, `__all__` and private
    typing helpers (`_T = TypeVar("_T")`, `type _X = ...`). Any other statement (an `if
    sys.version_info` branch, a public bare assignment or alias, `__all__ +=`) and a star import
    are reported, so nothing reaches mypy unchecked.
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
            name = f"{module}.{node.target.id}"
            if not exists(name):
                drift.append(f"{name}: no such name in the library")
            else:
                drift += attribute_drift(node, located(name), name)
        elif isinstance(node, ast.ImportFrom) and any(a.name == "*" for a in node.names):
            drift.append(f"{module}: line {node.lineno} re-exports with *; name each import")
        elif (exported := exported_names(node)) is not None:
            drift += [
                f"{module}.{name}: re-exported by the stub, not in the library"
                for name in exported
                if not exists(f"{module}.{name}")
            ]
        elif (
            isinstance(node, ast.Assign)
            and [ast.unparse(target) for target in node.targets] == ["__all__"]
            and (listed := all_names(node)) is not None
        ):
            drift += [
                f"{module}.{name}: listed in __all__, not in the library"
                for name in listed
                if not exists(f"{module}.{name}")
            ]
        elif not is_inert(node) and not is_typing_only(node):
            drift.append(f"{module}: line {node.lineno} is not a class, function or annotation")
    return drift
