"""Typed HTTP client for tests: the real application in process, lifespan included.

Starlette's TestClient is typed against an HTTP package the template does not install, so its
base class, and every response it returns, reaches mypy as Any. This client is typed end to
end instead (template-decisions.md, C2): requests go through httpx's ASGITransport (httpx is
typed and is a dev dependency), the lifespan runs through the ASGI lifespan protocol, as a
server runs it, and bodies are decoded by the template's own strict JSON decoder, so the
tests compare JsonValue.
"""

import asyncio
from collections.abc import AsyncIterator, MutableMapping
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx
from fastapi import FastAPI

from backend_logic._shared.json.contracts import JsonValue
from backend_logic._shared.json.decode.contracts import DecodeText
from backend_logic._shared.json.decode.run import run as decoding

# What the lifespan task puts on the reply queue when the application returns or raises.
ENDED = "ended"


@dataclass(frozen=True)
class WireResponse:
    status: int
    body: JsonValue

    def detail(self) -> JsonValue:
        """The error detail FastAPI puts under "detail"; fails if the body is not an object."""
        if not isinstance(self.body, dict):
            raise TypeError(f"expected a JSON object, got {self.body!r}")
        return self.body["detail"]


class WireClient:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def get(self, path: str) -> WireResponse:
        response = await self._client.get(path)
        return WireResponse(response.status_code, decoding(DecodeText(response.text)))

    async def put(self, path: str, content: bytes) -> WireResponse:
        response = await self._client.put(path, content=content)
        return WireResponse(response.status_code, decoding(DecodeText(response.text)))


@asynccontextmanager
async def running(app: FastAPI) -> AsyncIterator[None]:
    """Startup before the block and shutdown after it, through the ASGI lifespan protocol.

    A startup that fails re-raises the application's own exception here.
    """
    inbox: asyncio.Queue[dict[str, str]] = asyncio.Queue()
    replies: asyncio.Queue[str] = asyncio.Queue()

    async def receive() -> dict[str, str]:
        return await inbox.get()

    async def send(message: MutableMapping[str, object]) -> None:
        await replies.put(str(message["type"]))

    async def lifespan() -> None:
        scope: dict[str, object] = {"type": "lifespan", "asgi": {"version": "3.0"}}
        try:
            await app(scope, receive, send)
        finally:
            await replies.put(ENDED)

    task = asyncio.create_task(lifespan())
    await inbox.put({"type": "lifespan.startup"})
    if await replies.get() != "lifespan.startup.complete":
        await task
        raise RuntimeError("the application's lifespan did not start")
    try:
        yield
    finally:
        await inbox.put({"type": "lifespan.shutdown"})
        reply = await replies.get()
        await task
        if reply != "lifespan.shutdown.complete":
            raise RuntimeError(f"the application's lifespan did not shut down: {reply}")


@asynccontextmanager
async def serving(app: FastAPI) -> AsyncIterator[WireClient]:
    """Run the real application, lifespan included, for the duration of the block."""
    async with running(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield WireClient(client)
