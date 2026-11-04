"""Guard the shared vocabulary so new packages cannot drift from the guide silently.

Each rule cites docs/design/vertical-pipelines.md. A rule here that a real package needs to
break is a decision for the owner and architecture-log.md, not a reason to edit the scanner.
"""

import ast
from pathlib import Path
from typing import Literal

ROOT = Path(__file__).resolve().parents[2]
LOGIC = ROOT / "backend_logic"

FORBIDDEN_METHODS = {"have", "start", "create", "result", "build", "finish"}  # §3.1
CHILD_INTERNALS = {"pipeline", "container", "helpers"}  # §3.2: parent imports run/contracts
# §2: the file names are the map. A reader who knows nothing about the domain still knows
# where every package starts (run.py), what it holds (container.py) and what it trades
# (contracts.py). No other module name exists in backend_logic.
PACKAGE_FILES = ("__init__.py", "contracts.py", "container.py", "pipeline.py", "run.py")
# §2 (_shared): a package used by two or more neighbours lives in the `_shared/` of their nearest
# common parent. `_shared/` itself only groups (docstring); a grouping inside it (json/,
# storage/) holds the values every operation trades, and each operation is a package.
SHARED = "_shared"
SHARED_FILES = ("__init__.py",)
GROUPING_FILES = ("__init__.py", "contracts.py")


type FolderKind = Literal["shared", "grouping", "package"]


def logic_folders(logic: Path = LOGIC) -> list[Path]:
    folders = [logic, *(path for path in logic.rglob("*") if path.is_dir())]
    return sorted(folder for folder in folders if "__pycache__" not in folder.parts)


def folder_kind(folder: Path) -> FolderKind:
    """`_shared/` groups; a run-less child of `_shared/` is a grouping; the rest are packages."""
    if folder.name == SHARED:
        return "shared"
    if folder.parent.name == SHARED and not (folder / "run.py").exists():
        return "grouping"
    return "package"


def logic_packages(logic: Path = LOGIC) -> list[Path]:
    """Every folder that is not `_shared/` or a grouping has the five files (§2)."""
    return [folder for folder in logic_folders(logic) if folder_kind(folder) == "package"]


def is_shared(folder: Path, logic: Path = LOGIC) -> bool:
    return SHARED in folder.relative_to(logic).parts


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
        "from backend_logic.notes._shared.storage.write import run as writing\n"
        "from backend_logic.notes._shared.storage.write.contracts import WriteDocument\n"
        "from backend_logic.notes._shared.storage.write.pipeline import Pipe\n"
        "from backend_logic.notes._shared.storage.read import container\n"
    ) == [
        ".encode.pipeline",
        ".encode.container",
        "..name.helpers",
        "backend_logic.notes._shared.storage.write.pipeline.Pipe",
        "backend_logic.notes._shared.storage.read.container",
    ]
    assert has_match("match x:\n    case int():\n        pass\n")
    assert not has_match("if isinstance(x, int):\n    pass\n")
    assert declares_request_union("type NotesRequest = ListNotes | SaveNote\n")
    assert not declares_request_union("type NoteDocument = dict[str, JsonValue]\n")


def shape_violations(logic: Path) -> list[str]:
    """Folders whose modules differ from what their kind requires (§2)."""
    expected: dict[FolderKind, tuple[str, ...]] = {
        "shared": SHARED_FILES,
        "grouping": GROUPING_FILES,
        "package": PACKAGE_FILES,
    }
    found: list[str] = []
    for folder in logic_folders(logic):
        kind = folder_kind(folder)
        modules = sorted(path.name for path in folder.glob("*.py"))
        if modules != sorted(expected[kind]):
            found.append(f"{folder.relative_to(logic.parent)}: {kind} has {modules}")
        children = [p for p in folder.iterdir() if p.is_dir() and p.name != "__pycache__"]
        if kind != "package" and not children:
            found.append(f"{folder.relative_to(logic.parent)}: empty {kind}")
    return found


def test_every_folder_has_the_files_its_kind_requires() -> None:
    assert not shape_violations(LOGIC)


def test_shape_scanner_reports_every_kind(tmp_path: Path) -> None:
    five = {f"backend_logic/{name}": "" for name in PACKAGE_FILES}
    write_tree(
        tmp_path,
        {
            **five,
            "backend_logic/_shared/__init__.py": "",
            "backend_logic/_shared/contracts.py": "",  # _shared only groups
            "backend_logic/_shared/empty/__init__.py": "",  # grouping with nothing inside
            "backend_logic/_shared/empty/contracts.py": "",
        },
    )
    assert shape_violations(tmp_path / "backend_logic") == [
        "backend_logic/_shared: shared has ['__init__.py', 'contracts.py']",
        "backend_logic/_shared/empty: empty grouping",
    ]


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
    # §2 (_shared): a family is a door for use cases; nothing under _shared/ is one.
    shared_families = [str(p.relative_to(ROOT)) for p in families if is_shared(p)]
    shared_groupings = [
        str(folder.relative_to(ROOT))
        for folder in logic_folders()
        if folder_kind(folder) == "grouping" and is_family(folder)
    ]
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
    assert not shared_families
    assert not shared_groupings


def imported_runs(path: Path) -> list[Path]:
    """Package folders whose run module this file imports (`from <pkg> import run`)."""
    own = path.parent.relative_to(ROOT).parts
    found: list[Path] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.ImportFrom) or "run" not in {a.name for a in node.names}:
            continue
        parts = node.module.split(".") if node.module else []
        base = parts if node.level == 0 else [*own[: len(own) - node.level + 1], *parts]
        found.append(ROOT.joinpath(*base))
    return found


def has_overload(source: str) -> bool:
    return any(
        isinstance(node, ast.Name) and node.id == "overload" for node in ast.walk(ast.parse(source))
    )


def test_only_the_root_declares_overloads_and_only_parents_call_a_family() -> None:
    # §2: a family only dispatches and returns its <Family>Response union. The root's
    # overloads are the backend's public menu; an overload elsewhere is an unverified
    # promise (mypy does not check it against each case). A caller that needs an exact
    # product calls the process (_shared/json/encode, notes/_shared/storage/lock), never a
    # family; only the family's parent pipeline.py climbs into it.
    families = {package for package in logic_packages() if is_family(package)}
    overloaded = [
        str(package.relative_to(ROOT))
        for package in families
        if package != LOGIC and has_overload((package / "run.py").read_text(encoding="utf-8"))
    ]
    shortcuts = [
        f"{path.relative_to(ROOT)} -> {target.relative_to(ROOT)}"
        for path in LOGIC.rglob("*.py")
        for target in imported_runs(path)
        if target in families and path != target.parent / "pipeline.py"
    ]
    assert not overloaded
    assert not shortcuts


def nearest_folder(path: Path, logic: Path) -> Path | None:
    """The package folder an import target names, climbing from module or symbol to dir."""
    for candidate in (path, *path.parents):
        if candidate == logic.parent:
            return None
        if candidate.is_dir():
            return candidate
    return None


def imported_folders(path: Path, logic: Path) -> set[Path]:
    """Folders under logic this file imports from; a contracts-only import counts too.

    A neighbour that only uses another package's types still depends on its rule, so it is
    a consumer for §2 (_shared) the same as one that calls its run.
    """
    found: set[Path] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom):
            parts = node.module.split(".") if node.module else []
            if node.level == 0:
                if parts[:1] != [logic.name]:
                    continue
                base = logic.parent.joinpath(*parts)
            else:
                anchor = path.parent
                for _ in range(node.level - 1):
                    anchor = anchor.parent
                base = anchor.joinpath(*parts)
            targets = [base / alias.name for alias in node.names]
        elif isinstance(node, ast.Import):
            targets = [
                logic.parent.joinpath(*alias.name.split("."))
                for alias in node.names
                if alias.name.split(".")[0] == logic.name
            ]
        else:
            continue
        for target in targets:
            folder = nearest_folder(target, logic)
            if folder is not None and folder.is_relative_to(logic):
                found.add(folder)
    return found


def import_edges(logic: Path) -> list[tuple[Path, Path]]:
    """(importer folder, imported folder) for every backend module, own package excluded."""
    return [
        (path.parent, target)
        for path in logic.rglob("*.py")
        if "__pycache__" not in path.parts
        for target in imported_folders(path, logic)
        if target != path.parent
    ]


def neighbour(importer: Path, owner: Path) -> str | None:
    """Which child of owner an importer belongs to: `.` is owner itself; None is outside."""
    if not importer.is_relative_to(owner):
        return None
    parts = importer.relative_to(owner).parts
    if not parts:
        return "."
    if parts[0] == SHARED:
        return f"{SHARED}/{parts[1]}" if len(parts) > 1 else None
    return parts[0]


def use_case_names(family: Path) -> set[str]:
    """Names in the family's `<Family>Request` union."""
    tree = ast.parse((family / "contracts.py").read_text(encoding="utf-8"))
    return {
        name.id
        for node in tree.body
        if isinstance(node, ast.TypeAlias) and node.name.id.endswith("Request")
        for name in ast.walk(node.value)
        if isinstance(name, ast.Name)
    }


def is_use_case(package: Path) -> bool:
    """A family, or a package defining a request its parent family's union names."""
    if is_family(package):
        return True
    parent = package.parent
    if folder_kind(parent) != "package" or not is_family(parent):
        return False
    defined = {
        node.name
        for node in ast.parse((package / "contracts.py").read_text(encoding="utf-8")).body
        if isinstance(node, ast.ClassDef)
    }
    return bool(defined & use_case_names(parent))


def placement_violations(logic: Path) -> list[str]:
    """§2 (_shared): shared lives in `_shared/` at the nearest common parent, and only there."""
    edges = import_edges(logic)
    found: list[str] = []
    for folder in logic_folders(logic):
        name = str(folder.relative_to(logic.parent))
        if folder.parent.name == SHARED:
            owner = folder.parent.parent
            consumers = {
                key
                for importer, target in edges
                if target.is_relative_to(folder) and not importer.is_relative_to(folder)
                if (key := neighbour(importer, owner)) is not None
            }
            if len(consumers) < 2:
                found.append(f"{name}: shared by {sorted(consumers)}; move it into its user")
        if folder == logic or is_shared(folder, logic) or is_use_case(folder):
            continue
        parent = folder.parent
        users = {
            neighbour(importer, parent) or "outside"
            for importer, target in edges
            if target.is_relative_to(folder) and not importer.is_relative_to(folder)
        } - {"."}
        if len(users) >= 2 or "outside" in users:
            found.append(f"{name}: used by {sorted(users)}; move it to a _shared/")
    for importer, target in edges:
        parts = target.relative_to(logic).parts
        if SHARED not in parts:
            continue
        depth = len(parts) - 1 - parts[::-1].index(SHARED)
        owner = logic.joinpath(*parts[:depth])
        if not importer.is_relative_to(owner):
            found.append(
                f"{importer.relative_to(logic.parent)} reaches into "
                f"{target.relative_to(logic.parent)}, private to {owner.relative_to(logic.parent)}"
            )
    return found


def write_tree(root: Path, files: dict[str, str]) -> None:
    for relative, source in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")


def test_placement_scanner_reports_every_rule(tmp_path: Path) -> None:
    # Guards the guard on a synthetic tree: one shared package with a single user, one
    # helper used by two siblings outside _shared, one reach into a private _shared.
    write_tree(
        tmp_path,
        {
            "backend_logic/contracts.py": "type BackendRequest = A\n",
            "backend_logic/a/contracts.py": "class A: ...\n",
            "backend_logic/a/pipeline.py": "from backend_logic.a._shared.lone import run\n",
            "backend_logic/a/_shared/lone/contracts.py": "",
            "backend_logic/a/helper/contracts.py": "",
            "backend_logic/a/x/pipeline.py": "from ..helper import run\n",
            "backend_logic/a/x/contracts.py": "",
            "backend_logic/a/y/pipeline.py": "from backend_logic.a.helper.contracts import H\n",
            "backend_logic/a/y/contracts.py": "",
            "backend_logic/b/pipeline.py": "from backend_logic.a._shared.lone.contracts import L\n",
            "backend_logic/b/contracts.py": "",
        },
    )
    assert placement_violations(tmp_path / "backend_logic") == [
        # a's own pipeline is one user; b's import does not count, it is outside a.
        "backend_logic/a/_shared/lone: shared by ['.']; move it into its user",
        # A contracts-only import (y) counts as much as calling run (x).
        "backend_logic/a/helper: used by ['x', 'y']; move it to a _shared/",
        "backend_logic/b reaches into backend_logic/a/_shared/lone, private to backend_logic/a",
    ]


def test_shared_packages_sit_at_the_nearest_common_parent() -> None:
    assert not placement_violations(LOGIC)


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
            if isinstance(target, ast.Attribute):
                name = target.attr
            elif isinstance(target, ast.Name):
                name = target.id
            else:
                continue
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


def test_run_composition_has_no_formatter_escapes() -> None:
    # §4.1: pyproject skips run.py once (checked in test_config.py), so no file needs `# fmt:`.
    escapes = [
        str(path.relative_to(ROOT))
        for path in LOGIC.rglob("*.py")
        if "# fmt:" in path.read_text(encoding="utf-8")
    ]
    assert not escapes


ADAPTER = ROOT / "http_adapter"
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
        for folder in (LOGIC, ADAPTER)
        for path in folder.rglob("*.py")
        for module in eager_imports(path.read_text(encoding="utf-8"))
    ]
    assert not violations, "write `lazy import`, or add the module to EAGER_IMPORTS with why"
