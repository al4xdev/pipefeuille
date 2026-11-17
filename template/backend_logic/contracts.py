"""Every use case the backend answers; read run.py next to see where each one goes.

Each type lives in the package that owns it. Families never import this module, so it
can import theirs without a cycle. DecodeText and EncodeValue are answered here by the
shared json operations: the HTTP edge needs the same strict JSON as the backend. OpenHarness
is answered by the agent-runs port's harness adapter: the HTTP application opens it once, in
its lifespan, and passes it to the use cases that run agents.
"""

lazy from ._shared.agents.harness.contracts import OpenHarness
lazy from ._shared.json.decode.contracts import DecodeText
lazy from ._shared.json.encode.contracts import EncodeValue
lazy from .notes.contracts import NotesRequest
lazy from .roles.contracts import RolesRequest

type BackendRequest = NotesRequest | RolesRequest | DecodeText | EncodeValue | OpenHarness
