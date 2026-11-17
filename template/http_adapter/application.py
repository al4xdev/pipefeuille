"""HTTP application assembly; resource ownership stays in backend_logic.notes.prepare."""

lazy from collections.abc import AsyncIterator
lazy from contextlib import asynccontextmanager
lazy from pathlib import Path

lazy from fastapi import FastAPI

lazy from backend_logic import run as backend
lazy from backend_logic._shared.agents.contracts import AgentRuns
lazy from backend_logic._shared.agents.harness.contracts import OpenHarness
lazy from backend_logic.notes.prepare.contracts import PrepareResources
lazy from backend_logic.notes.save.contracts import AuthorId

lazy from .lifetime import ResourceSlot
lazy from .notes.routes import build_router


def create_app(*, data_root: Path, agents: OpenHarness | AgentRuns) -> FastAPI:
    """Called by the process entrypoint, never at import time. Nothing touches disk until
    the lifespan starts; requests before that fail instead of using half-built state.

    agents: where the harness server listens (opened in the lifespan, which sends nothing),
    or an AgentRuns the caller already holds (tests pass a typed fake).
    """
    slot = ResourceSlot()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        slot.resources = await backend.run(
            PrepareResources(data_root=data_root, author_id=AuthorId("owner"))
        )
        slot.agents = await backend.run(agents) if isinstance(agents, OpenHarness) else agents
        yield

    app = FastAPI(lifespan=lifespan)
    app.include_router(build_router(slot=slot))
    return app
