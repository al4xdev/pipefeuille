"""Guard the shared vocabulary so new packages cannot drift from the guide silently.

Each rule cites docs/design/vertical-pipelines.md. A rule here that a real package needs to
break is a decision for the owner and architecture-log.md, not a reason to edit the scanner.
"""

import ast
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOGIC = ROOT / "backend_logic"

FORBIDDEN_METHODS = {"have", "start", "create", "result", "build", "finish"}  # §3.1
CHILD_INTERNALS = {"pipeline", "container", "helpers"}  # §3.2: parent imports run/contracts
# §2: the file names are the map. A reader who knows nothing about the domain still knows
# where every package starts (run.py), what it holds (container.py) and what it trades
# (contracts.py). No other module name exists in backend_logic.
PACKAGE_FILES = ("__init__.py", "contracts.py", "container.py", "pipeline.py", "run.py")


def logic_packages() -> list[Path]:
    """Every folder in backend_logic is a package, the root included (§2)."""
    folders = [LOGIC, *(path for path in LOGIC.rglob("*") if path.is_dir())]
    return sorted(folder for folder in folders if "__pycache__" not in folder.parts)


def pipe_class(tree: ast.Module) -> ast.ClassDef | None:
    return next(
        (node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Pipe"),
        None,
    )


def method_names(pipe: ast.ClassDef) -> list[str]:
    return [
        node.name for node in pipe.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def style_violations(source: str) -> list[str]:
    """Violations of the Pipe contract in one pipeline.py source."""
    tree = ast.parse(source)
    pipe = pipe_class(tree)
    if pipe is None:
        return ["pipeline.py must define class Pipe"]
    violations: list[str] = []
    names = method_names(pipe)
    for required in ("__init__", "get", "materialize"):
        if required not in names:
            violations.append(f"Pipe.{required} is missing")
    aliases = sorted(FORBIDDEN_METHODS & set(names))
    violations.extend(f"Pipe.{name} is a forbidden alias" for name in aliases)
    for statement in pipe.body:
        if not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if statement.name != "__init__" and ast.get_docstring(statement) is None:
            violations.append(f"Pipe.{statement.name} has no docstring contract")  # §3.5
        if statement.name not in ("__init__", "get", "materialize") and not (
            isinstance(statement.returns, ast.Name) and statement.returns.id == "Self"
        ):
            violations.append(f"Pipe.{statement.name} must return Self")  # §3.1
    for node in ast.walk(pipe):
        # §3.1: self.container is the only home of intermediates.
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "self"
            and isinstance(node.ctx, ast.Store)
            and node.attr != "container"
        ):
            violations.append(f"self.{node.attr} is assigned outside self.container")
    return violations


def child_internal_imports(source: str) -> list[str]:
    """Imports reaching into another package's pipeline/container/helpers.

    Relative imports may name their own package's modules (`from .container import ...`);
    absolute backend_logic imports never may, since they always cross a package.
    """
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.ImportFrom):
            continue
        parts = node.module.split(".") if node.module else []
        if node.level == 0:
            if parts[:1] == ["backend_logic"]:
                found.extend(
                    f"{node.module}.{alias.name}"
                    for alias in node.names
                    if CHILD_INTERNALS & {*parts, alias.name}
                )
            continue
        own_module = node.level == 1 and len(parts) == 1  # `from .container import Container`
        if not own_module and CHILD_INTERNALS & set(parts):
            found.append("." * node.level + (node.module or ""))
        found.extend(
            "." * node.level + (node.module or "") + "." + alias.name
            for alias in node.names
            if alias.name in CHILD_INTERNALS
        )
    return found


def has_match(source: str) -> bool:
    return any(isinstance(node, ast.Match) for node in ast.walk(ast.parse(source)))


def declares_request_union(source: str) -> bool:
    """A family names its use cases as `type <Family>Request = A | B` in contracts.py."""
    return any(
        isinstance(node, ast.TypeAlias) and node.name.id.endswith("Request")
        for node in ast.parse(source).body
    )


def is_family(package: Path) -> bool:
    return declares_request_union((package / "contracts.py").read_text(encoding="utf-8"))


def test_style_scanner_reports_every_rule() -> None:
    # Guards the guard: each rule must fire on a source that breaks it.
    bad = (
        "class Pipe:\n"
        "    def __init__(self) -> None:\n"
        "        self.state = None\n"
        "    def have(self) -> 'Pipe':\n"
        "        return self\n"
    )
    assert style_violations(bad) == [
        "Pipe.get is missing",
        "Pipe.materialize is missing",
        "Pipe.have is a forbidden alias",
        "Pipe.have has no docstring contract",
        "Pipe.have must return Self",
        "self.state is assigned outside self.container",
    ]
    assert style_violations("class Other: pass\n") == ["pipeline.py must define class Pipe"]
    assert child_internal_imports(
        "from .container import Container\n"
        "from .encode import run as encoding\n"
        "from .encode import pipeline\n"
        "from .encode.container import Container\n"
        "from ..name.helpers import trim\n"
        "from backend_logic.storage import run as storing\n"
        "from backend_logic.storage.write.contracts import WriteDocument\n"
        "from backend_logic.storage.write.pipeline import Pipe\n"
        "from backend_logic.storage.read import container\n"
    ) == [
        ".encode.pipeline",
        ".encode.container",
        "..name.helpers",
        "backend_logic.storage.write.pipeline.Pipe",
        "backend_logic.storage.read.container",
    ]
    assert has_match("match x:\n    case int():\n        pass\n")
    assert not has_match("if isinstance(x, int):\n    pass\n")
    assert declares_request_union("type NotesRequest = ListNotes | SaveNote\n")
    assert not declares_request_union("type NoteDocument = dict[str, JsonValue]\n")


def test_every_folder_is_a_package_with_the_mandatory_files() -> None:
    missing = [
        f"{package.relative_to(ROOT)}/{name}"
        for package in logic_packages()
        for name in PACKAGE_FILES
        if not (package / name).is_file()
    ]
    assert not missing


def test_no_module_outside_the_mandatory_names() -> None:
    # A loose jsonvalue.py or files.py hides where reading starts; it becomes a package.
    loose = [
        str(path.relative_to(ROOT))
        for path in LOGIC.rglob("*.py")
        if "__pycache__" not in path.parts and path.name not in PACKAGE_FILES
    ]
    assert not loose


def test_every_family_run_dispatches_by_typed_use_case() -> None:
    # The climb: backend_logic/run.py is a family, each family's run shows its branches with
    # match, and no family hides beneath a process. Children of a process (save/decode,
    # save/encode) are its stages, not use cases, so a process needs no dispatch.
    families = [package for package in logic_packages() if is_family(package)]
    assert LOGIC in families
    silent = [
        str(package.relative_to(ROOT))
        for package in families
        if not has_match((package / "run.py").read_text(encoding="utf-8"))
    ]
    broken_climb = [
        str(package.relative_to(ROOT))
        for package in families
        if package != LOGIC and not is_family(package.parent)
    ]
    assert not silent
    assert not broken_climb


def test_package_init_is_a_docstring_without_startup() -> None:
    # §2: __init__.py identifies the package; no I/O, config or startup on import.
    violations: list[str] = []
    for init in LOGIC.rglob("__init__.py"):
        tree = ast.parse(init.read_text(encoding="utf-8"))
        if ast.get_docstring(tree) is None or len(tree.body) != 1:
            violations.append(str(init.relative_to(ROOT)))
    assert not violations


def test_every_pipe_follows_the_vocabulary() -> None:
    violations = [
        (str(package.relative_to(ROOT)), violation)
        for package in logic_packages()
        for violation in style_violations((package / "pipeline.py").read_text(encoding="utf-8"))
    ]
    assert not violations


def test_parents_import_only_the_public_run_and_contracts_of_children() -> None:
    violations = [
        (str(path.relative_to(ROOT)), module)
        for path in LOGIC.rglob("*.py")
        for module in child_internal_imports(path.read_text(encoding="utf-8"))
    ]
    assert not violations


def test_logic_never_uses_assert_for_preconditions() -> None:
    # §5: python -O strips asserts; required fields fail with an explicit raise.
    violations = [
        str(path.relative_to(ROOT))
        for path in LOGIC.rglob("*.py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Assert)
    ]
    assert not violations


CLOSED_NAMES = {"code", "phase"}  # §6: finite choices are Literal/Enum, not str


def open_closed_names(source: str) -> list[str]:
    """Parameters and attributes named code/phase annotated as bare str."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.arg) and node.arg in CLOSED_NAMES:
            annotation, name = node.annotation, node.arg
        elif isinstance(node, ast.AnnAssign):
            target = node.target
            name = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", "")
            annotation = node.annotation
        else:
            continue
        if name in CLOSED_NAMES and isinstance(annotation, ast.Name) and annotation.id == "str":
            found.append(name)
    return found


def test_closed_name_scanner_reports_bare_str() -> None:
    source = (
        "class E(ValueError):\n"
        "    def __init__(self, code: str, phase: Phase) -> None:\n"
        "        self.code: str = code\n"
    )
    assert open_closed_names(source) == ["code", "code"]


def test_error_codes_and_phases_are_closed_sets() -> None:
    # A delegated implementer can't invent a client-facing code in a raise; the type lists them.
    violations = [
        f"{path.relative_to(ROOT)}: {name}"
        for path in LOGIC.rglob("*.py")
        for name in open_closed_names(path.read_text(encoding="utf-8"))
    ]
    assert not violations


def test_run_composition_is_left_to_the_author_not_the_formatter() -> None:
    # §4.1: the formatter is configured once in pyproject to skip run.py, so no file needs a
    # `# fmt:` escape. force-exclude keeps editors that pass a path from reformatting it.
    ruff = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["ruff"]
    assert ruff["force-exclude"] is True
    assert {"backend_logic/**/run.py", "docs/**/*.md"} <= set(ruff["format"]["exclude"])
    escapes = [
        str(path.relative_to(ROOT))
        for path in LOGIC.rglob("*.py")
        if "# fmt:" in path.read_text(encoding="utf-8")
    ]
    assert not escapes


FRONTEND = ROOT / "backend_frontend"
# §6.1 fallback: a top-level module that breaks under PEP 810 (import-time registration,
# side effects the code relies on) goes here with the reason, and is imported eagerly.
# Record the entry in architecture-log.md too. Keys are the imported module as written.
EAGER_IMPORTS: dict[str, str] = {}


def eager_imports(source: str) -> list[str]:
    """Top-level imports written without `lazy`, except those PEP 810 forbids or allows."""
    found: list[str] = []
    for node in ast.parse(source).body:
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            module = "." * node.level + (node.module or "")
            if module == "__future__":  # cannot be lazy
                continue
            modules = [module]
        else:
            continue
        if not node.is_lazy:
            found.extend(module for module in modules if module not in EAGER_IMPORTS)
    return found


def test_eager_import_scanner_reports_only_top_level_eager_imports() -> None:
    source = (
        "from __future__ import annotations\n"
        "lazy import json\n"
        "import os\n"
        "lazy from .contracts import A\n"
        "from .pipeline import Pipe\n"
        "def run() -> None:\n"
        "    import sys\n"  # function scope cannot be lazy; not reported
    )
    assert eager_imports(source) == ["os", ".pipeline"]


def test_every_top_level_import_is_lazy() -> None:
    # §6.1: a module costs nothing until its first use; startup loads only the path it takes.
    violations = [
        f"{path.relative_to(ROOT)}: {module}"
        for folder in (LOGIC, FRONTEND)
        for path in folder.rglob("*.py")
        for module in eager_imports(path.read_text(encoding="utf-8"))
    ]
    assert not violations, "write `lazy import`, or add the module to EAGER_IMPORTS with why"
