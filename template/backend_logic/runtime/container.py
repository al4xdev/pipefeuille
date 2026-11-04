lazy from dataclasses import dataclass

lazy from .application.contracts import Resources
lazy from .contracts import RuntimeRequest


@dataclass
class Container:
    input: RuntimeRequest | None = None
    resources: Resources | None = None
