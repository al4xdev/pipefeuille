lazy from typing import Self

lazy from ._shared.json.contracts import JsonValue, Validated
lazy from ._shared.json.decode import run as decoding
lazy from ._shared.json.decode.contracts import DecodeText
lazy from ._shared.json.encode import run as encoding
lazy from ._shared.json.encode.contracts import EncodeValue
lazy from .container import Container
lazy from .contracts import BackendRequest
lazy from .notes import run as noting
lazy from .notes.contracts import NotesRequest, NotesResponse
lazy from .notes.prepare.contracts import Resources
lazy from .roles import run as roling
lazy from .roles.contracts import RolesRequest, RolesResponse
lazy from .roles.summarizer.contracts import Model


class Pipe:
    def __init__(self) -> None:
        self.container = Container()

    @classmethod
    def get(cls, initial: BackendRequest) -> Self:
        """Set input unchanged; run chooses the branch."""
        pipe = cls()
        pipe.container.input = initial
        return pipe

    async def serve_notes(self, request: NotesRequest, *, resources: Resources | None) -> Self:
        """Set notes through the notes family, which prepares and then uses its resources."""
        self.container.notes = await noting.run(request, resources=resources)
        return self

    async def serve_roles(self, request: RolesRequest, *, model: Model) -> Self:
        """Set roles through the roles family; the caller supplies and owns the model."""
        self.container.roles = await roling.run(request, model=model)
        return self

    def decode_json(self, request: DecodeText) -> Self:
        """Set converted through the shared strict decoder. Rejection is ValueError."""
        self.container.converted = Validated(decoding.run(request))
        return self

    def encode_json(self, request: EncodeValue) -> Self:
        """Set converted through the shared strict encoder. Rejection is ValueError/TypeError."""
        self.container.converted = Validated(encoding.run(request))
        return self

    def materialize(self) -> NotesResponse | RolesResponse | JsonValue:
        """Require exactly the branch that ran; return its product."""
        if self.container.notes is not None:
            return self.container.notes
        if self.container.roles is not None:
            return self.container.roles
        if self.container.converted is not None:
            return self.container.converted.value
        raise RuntimeError("a backend branch must run before materialize")
