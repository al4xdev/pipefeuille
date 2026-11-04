lazy from dataclasses import dataclass

lazy from .contracts import BackendRequest
lazy from .json.validate.contracts import Validated
lazy from .notes.contracts import NotesResponse
lazy from .roles.contracts import RolesResponse
lazy from .runtime.application.contracts import Resources


@dataclass
class Container:
    input: BackendRequest | None = None
    resources: Resources | None = None
    notes: NotesResponse | None = None
    roles: RolesResponse | None = None
    # Wrapped: decoding JSON null is a legitimate product, not "branch not run".
    converted: Validated | None = None
