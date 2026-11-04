"""HTTP application assembly; resource ownership stays in backend_logic.runtime."""

lazy from collections.abc import AsyncIterator
lazy from contextlib import asynccontextmanager
lazy from pathlib import Path

lazy from fastapi import FastAPI

lazy from backend_logic import run as backend
lazy from backend_logic.notes.save.contracts import AuthorId
lazy from backend_logic.runtime.application.contracts import PrepareResources

lazy from .lifetime import ResourceSlot
lazy from .notes.routes import build_router


def create_app(*, data_root: Path) -> FastAPI:
    """Called by the process entrypoint, never at import time. Nothing touches disk until
    the lifespan starts; requests before that fail instead of using half-built state."""
    slot = ResourceSlot()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        slot.resources = await backend.run(
            PrepareResources(data_root=data_root, author_id=AuthorId("owner"))
        )
        yield

    app = FastAPI(lifespan=lifespan)
    app.include_router(build_router(slot=slot))
    return app
