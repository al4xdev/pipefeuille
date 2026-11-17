lazy from typing import Self
lazy from urllib.parse import urlsplit

lazy from backend_logic._shared.json.contracts import JsonValue
lazy from backend_logic._shared.json.decode import run as decoding
lazy from backend_logic._shared.json.decode.contracts import DecodeText
lazy from backend_logic._shared.json.encode import run as encoding
lazy from backend_logic._shared.json.encode.contracts import EncodeValue

lazy from .container import Container
lazy from .contracts import HarnessAgents, OpenHarness


class Pipe:
    def __init__(self) -> None:
        self.container = Container()

    @classmethod
    def get(cls, initial: OpenHarness) -> Self:
        """Set input unchanged; nothing is opened or sent."""
        pipe = cls()
        pipe.container.input = initial
        return pipe

    def validate_url(self, *, schemes: frozenset[str]) -> Self:
        """Require input; set base_url without a trailing slash. A URL with another scheme, no
        host, or a path, query or fragment is a ValueError: routes are appended to it."""
        if self.container.input is None:
            raise RuntimeError("opening the harness requires input")
        parts = urlsplit(self.container.input.base_url)
        if parts.scheme not in schemes or not parts.hostname:
            raise ValueError("the harness URL needs a scheme and a host")
        if parts.path not in ("", "/") or parts.query or parts.fragment:
            raise ValueError("the harness URL is a base: no path, query or fragment")
        if not self.container.input.timeout_seconds > 0:
            raise ValueError("the harness timeout must be positive")
        self.container.base_url = self.container.input.base_url.rstrip("/")
        return self

    def bind_json(self) -> Self:
        """Set read_json and write_json: the shared strict decoder and encoder, the only JSON
        the adapter may use (never the HTTP client's). No I/O."""

        def read_json(text: str) -> JsonValue:
            return decoding.run(DecodeText(text))

        def write_json(value: JsonValue) -> str:
            return encoding.run(EncodeValue(value))

        self.container.read_json = read_json
        self.container.write_json = write_json
        return self

    def materialize(self) -> HarnessAgents:
        """Require base_url and the JSON pair; return the adapter, which holds no connection."""
        initial, base_url = self.container.input, self.container.base_url
        read_json, write_json = self.container.read_json, self.container.write_json
        if initial is None or base_url is None or read_json is None or write_json is None:
            raise RuntimeError("the harness adapter is incomplete")
        return HarnessAgents(
            base_url,
            timeout=initial.timeout_seconds,
            read_json=read_json,
            write_json=write_json,
        )
