"""Every use case the backend answers; read run.py next to see where each one goes.

Each type lives in the package that owns it. Families never import this module, so it
can import theirs without a cycle.
"""

lazy from .json.contracts import JsonRequest
lazy from .notes.contracts import NotesRequest
lazy from .roles.contracts import RolesRequest
lazy from .runtime.contracts import RuntimeRequest

type BackendRequest = RuntimeRequest | NotesRequest | RolesRequest | JsonRequest
