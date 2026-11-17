lazy from typing import assert_never

lazy from backend_logic._shared.agents.contracts import AgentRuns

lazy from .contracts import NotesRequest, NotesResponse
lazy from .list.contracts import ListNotes
lazy from .pipeline import Pipe
lazy from .prepare.contracts import PrepareResources, Resources
lazy from .save.contracts import SaveNote
lazy from .summarize.contracts import DispatchSummary
lazy from .summary.contracts import ReadSummary


async def run(
    initial: NotesRequest, *, resources: Resources | None, agents: AgentRuns | None
) -> NotesResponse:
    """Example domain: user notes, used to demonstrate the package language."""
    pipe = Pipe.get(initial)
    match initial:
        case PrepareResources():
            pipe.prepare_resources(initial)
        case ListNotes():
            if resources is None:
                raise RuntimeError("listing notes requires the prepared resources")
            pipe.list_notes(initial, resources=resources)
        case SaveNote():
            if resources is None:
                raise RuntimeError("saving a note requires the prepared resources")
            await pipe.save_note(initial, resources=resources)
        case DispatchSummary():
            if resources is None or agents is None:
                raise RuntimeError("summarizing a note requires the resources and the agents")
            await pipe.summarize_note(initial, resources=resources, agents=agents)
        case ReadSummary():
            if resources is None or agents is None:
                raise RuntimeError("reading a summary requires the resources and the agents")
            await pipe.read_summary(initial, resources=resources, agents=agents)
        case _:
            assert_never(initial)
    return pipe.materialize()
