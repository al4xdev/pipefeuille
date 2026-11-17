lazy from dataclasses import dataclass

lazy from backend_logic._shared.agents.contracts import Observation
lazy from backend_logic._shared.json.contracts import JsonValue

lazy from .contracts import NoteSummary, ReadSummary


@dataclass
class Container:
    input: ReadSummary | None = None
    observation: Observation | None = None
    answer: JsonValue | None = None  # the decoded output, not yet admitted
    summary: NoteSummary | None = None
