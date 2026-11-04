lazy from typing import Self

lazy from .application import run as preparing
lazy from .application.contracts import PrepareResources, Resources
lazy from .container import Container
lazy from .contracts import RuntimeRequest


class Pipe:
    def __init__(self) -> None:
        self.container = Container()

    @classmethod
    def get(cls, initial: RuntimeRequest) -> Self:
        """Set input unchanged; run chooses the branch."""
        pipe = cls()
        pipe.container.input = initial
        return pipe

    def prepare_resources(self, request: PrepareResources) -> Self:
        """Set resources through the application child. Creates the data root once."""
        self.container.resources = preparing.run(request)
        return self

    def materialize(self) -> Resources:
        """Require resources; return them without constructing new ones."""
        if self.container.resources is None:
            raise RuntimeError("a runtime branch must run before materialize")
        return self.container.resources
