"""Hold the resources the backend prepared for this application lifetime."""

lazy from dataclasses import dataclass

lazy from backend_logic._shared.agents.contracts import AgentRuns
lazy from backend_logic.notes.prepare.contracts import Resources


@dataclass
class ResourceSlot:
    """Filled once by the lifespan before any request is served; empty means not started."""

    resources: Resources | None = None
    agents: AgentRuns | None = None

    def require(self) -> Resources:
        if self.resources is None:
            raise RuntimeError("application resources are prepared by the lifespan")
        return self.resources

    def require_agents(self) -> AgentRuns:
        if self.agents is None:
            raise RuntimeError("the agent-runs port is opened by the lifespan")
        return self.agents
