lazy from dataclasses import dataclass

lazy from ._shared.json.contracts import Validated
lazy from .contracts import BackendRequest
lazy from .notes.contracts import NotesResponse
lazy from .roles.contracts import RolesResponse


@dataclass
class Container:
    input: BackendRequest | None = None
    notes: NotesResponse | None = None
    roles: RolesResponse | None = None
    # Wrapped: decoding JSON null is a legitimate product, not "branch not run".
    converted: Validated | None = None
