lazy from dataclasses import dataclass

lazy from .contracts import RolesRequest, RolesResponse


@dataclass
class Container:
    input: RolesRequest | None = None
    response: RolesResponse | None = None
