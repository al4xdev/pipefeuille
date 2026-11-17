# typeshed types tomllib.loads as dict[str, Any], which disallow_any_expr rejects in every
# expression that touches the result. This stub (on mypy_path, so it replaces typeshed's for
# the whole project) declares the same functions with `object` values: every reader narrows
# them with isinstance before use. It declares only what the template uses; anything else
# from tomllib is an error until it is declared here. Checked against the installed module by
# tests/gates/test_boundaries.py::test_every_stub_matches_the_installed_library
# (template-decisions C2).
from collections.abc import Callable

class TOMLDecodeError(ValueError): ...

def loads(s: str, /, *, parse_float: Callable[[str], object] = ...) -> dict[str, object]: ...
