lazy from typing import Self

lazy from .container import Container
lazy from .contracts import BackendRequest
lazy from .json import run as converting
lazy from .json.contracts import JsonRequest
lazy from .json.validate.contracts import JsonValue, Validated
lazy from .notes import run as noting
lazy from .notes.contracts import NotesRequest, NotesResponse
lazy from .roles import run as roling
lazy from .roles.contracts import RolesRequest, RolesResponse
lazy from .roles.summarizer.contracts import Model
lazy from .runtime import run as preparing
lazy from .runtime.application.contracts import Resources
lazy from .runtime.contracts import RuntimeRequest


class Pipe:
    def __init__(self) -> None:
        self.container = Container()

    @classmethod
    def get(cls, initial: BackendRequest) -> Self:
        """Set input unchanged; run chooses the family."""
        pipe = cls()
        pipe.container.input = initial
        return pipe

    def prepare_resources(self, request: RuntimeRequest) -> Self:
        """Set resources through runtime. Called once per application lifetime."""
        self.container.resources = preparing.run(request)
        return self

    async def serve_notes(self, request: NotesRequest, *, resources: Resources) -> Self:
        """Set notes through the notes family with the lifetime's store, locks and clock."""
        self.container.notes = await noting.run(
            request, store=resources.store, locks=resources.locks, clock=resources.clock
        )
        return self

    async def serve_roles(self, request: RolesRequest, *, model: Model) -> Self:
        """Set roles through the roles family; the caller supplies and owns the model."""
        self.container.roles = await roling.run(request, model=model)
        return self

    def convert_json(self, request: JsonRequest) -> Self:
        """Set converted through the strict json family. Rejection is ValueError."""
        self.container.converted = Validated(converting.run(request))
        return self

    def materialize(self) -> Resources | NotesResponse | RolesResponse | JsonValue:
        """Require exactly the family that ran; return its product."""
        if self.container.resources is not None:
            return self.container.resources
        if self.container.notes is not None:
            return self.container.notes
        if self.container.roles is not None:
            return self.container.roles
        if self.container.converted is not None:
            return self.container.converted.value
        raise RuntimeError("a backend family must run before materialize")
