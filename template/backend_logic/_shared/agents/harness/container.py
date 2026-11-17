lazy from dataclasses import dataclass

lazy from .contracts import JsonReader, JsonWriter, OpenHarness


@dataclass
class Container:
    input: OpenHarness | None = None
    base_url: str | None = None
    read_json: JsonReader | None = None
    write_json: JsonWriter | None = None
