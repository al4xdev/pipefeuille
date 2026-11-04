"""Typed HTTP client for tests: the one place the untyped TestClient is touched.

Starlette's TestClient reaches mypy as Any, so every call on it would carry Any into the
test bodies. This adapter is a recorded boundary (pyproject override, template-decisions.md C2):
it returns the status and a body decoded by the template's own strict JSON decoder, so the
tests compare JsonValue, not Any.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend_logic._shared.json.contracts import JsonValue
from backend_logic._shared.json.decode.contracts import DecodeText
from backend_logic._shared.json.decode.run import run as decoding


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
    def __init__(self, client: TestClient) -> None:
        self._client = client

    def get(self, path: str) -> WireResponse:
        response = self._client.get(path)
        return self._wrap(response.status_code, response.text)

    def put(self, path: str, content: bytes) -> WireResponse:
        response = self._client.put(path, content=content)
        return self._wrap(response.status_code, response.text)

    @staticmethod
    def _wrap(status: object, text: object) -> WireResponse:
        if not isinstance(status, int) or not isinstance(text, str):
            raise TypeError("TestClient returned an unexpected response shape")
        return WireResponse(status=status, body=decoding(DecodeText(text)))


@contextmanager
def serving(app: FastAPI) -> Iterator[WireClient]:
    """Run the real application, lifespan included, for the duration of the block."""
    with TestClient(app) as client:
        yield WireClient(client)
