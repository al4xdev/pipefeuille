"""Guard the dependency direction before implementation grows around it."""

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOGIC = ROOT / "backend_logic"
HTTP = ROOT / "backend_frontend"


def absolute_imports(source: str) -> list[str]:
    """Dotted targets, including names: `from a.b import c` yields both a.b and a.b.c."""
    tree = ast.parse(source)
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.append(node.module)
            modules.extend(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def frontend_logic_imports(source: str) -> list[str]:
    """backend_logic targets other than the root run and contracts modules (and their names).

    The HTTP adapter enters through backend_logic/run.py like every other caller; a family
    run, a pipeline or a container is never its door.
    """
    allowed = {"backend_logic", "backend_logic.run"}
    return [
        module
        for module in absolute_imports(source)
        if module.split(".")[0] == "backend_logic"
        and module not in allowed
        and "contracts" not in module.split(".")
    ]


def test_logic_does_not_import_http() -> None:
    forbidden = {"backend_frontend", "fastapi", "starlette", "pydantic"}
    violations = [
        (str(path.relative_to(ROOT)), module)
        for path in LOGIC.rglob("*.py")
        for module in absolute_imports(path.read_text(encoding="utf-8"))
        if module.split(".")[0] in forbidden
    ]
    assert not violations


def test_internal_import_scanner_sees_every_import_form() -> None:
    # Guards the guard: a scanner that only read node.module was vacuously green.
    source = (
        "from backend_logic.notes.save import pipeline\n"
        "from backend_logic.notes import run\n"
        "import backend_logic.notes.list.container\n"
        "from backend_logic import run as backend\n"
        "from backend_logic.notes.save.contracts import SaveNote\n"
    )
    assert frontend_logic_imports(source) == [
        "backend_logic.notes.save",
        "backend_logic.notes.save.pipeline",
        "backend_logic.notes",
        "backend_logic.notes.run",
        "backend_logic.notes.list.container",
    ]


def test_http_enters_only_through_the_root_run() -> None:
    violations = [
        (str(path.relative_to(ROOT)), module)
        for path in HTTP.rglob("*.py")
        for module in frontend_logic_imports(path.read_text(encoding="utf-8"))
    ]
    assert not violations


def test_run_modules_contain_a_real_run_definition() -> None:
    for path in LOGIC.rglob("run.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assert any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "run"
            for node in tree.body
        ), f"{path.relative_to(ROOT)} must own its composition, not just re-export it"


def test_package_imports_do_not_open_private_data_or_network(tmp_path: Path) -> None:
    script = """
import importlib
import os
import pathlib
import pkgutil
import sys

root = pathlib.Path(sys.argv[1]).resolve()
# Audit hooks cannot be removed; this flag disarms it for the test's own final check.
importing = True

def audit(event, args):
    if not importing:
        return
    if event.startswith('socket.'):
        raise AssertionError('Package import attempted network access')
    # Directory creation/listing emits os.* events, not 'open'.
    events = {'open', 'os.mkdir', 'os.listdir', 'os.scandir', 'os.remove', 'os.rename'}
    if event in events and args and isinstance(args[0], (str, bytes, os.PathLike)):
        path = pathlib.Path(os.fsdecode(args[0]))
        if '.data' in path.parts or '.dumps' in path.parts:
            raise AssertionError('Package import attempted private data access')
        if path.resolve().is_relative_to(root):
            raise AssertionError('Package import attempted runtime data access')

sys.addaudithook(audit)
import backend_logic
import backend_frontend

for package in (backend_logic, backend_frontend):
    for module in pkgutil.walk_packages(package.__path__, package.__name__ + '.'):
        importlib.import_module(module.name)
importing = False
assert not list(root.iterdir())
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", script, str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_private_material_is_git_ignored() -> None:
    lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".data/" in lines
    assert ".dumps/" in lines
