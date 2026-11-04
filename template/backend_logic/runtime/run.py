lazy from typing import assert_never

lazy from .application.contracts import PrepareResources, Resources
lazy from .contracts import RuntimeRequest
lazy from .pipeline import Pipe


def run(initial: RuntimeRequest) -> Resources:
    pipe = Pipe.get(initial)
    match initial:
        case PrepareResources():
            pipe.prepare_resources(initial)
        case _:
            assert_never(initial)
    return pipe.materialize()
