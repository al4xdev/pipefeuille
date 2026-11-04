"""Hold the resources the backend prepared for this application lifetime."""

lazy from dataclasses import dataclass

lazy from backend_logic.runtime.application.contracts import Resources


@dataclass
class ResourceSlot:
    """Filled once by the lifespan before any request is served; empty means not started."""

    resources: Resources | None = None

    def require(self) -> Resources:
        if self.resources is None:
            raise RuntimeError("application resources are prepared by the lifespan")
        return self.resources
