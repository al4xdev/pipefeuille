lazy from .contracts import HarnessAgents, OpenHarness
lazy from .pipeline import Pipe


def run(initial: OpenHarness) -> HarnessAgents:
    """Open the agent-runs port on the harness server: the adapter, with its strict JSON bound.

    HarnessAgents (contracts.py) is the port. Opening it sends nothing; each of its methods is
    one POST to the harness on loopback (/dispatch, /status), and the use cases that call them
    declare that effect. Opened once per application lifetime, by the HTTP application's
    lifespan, through backend_logic.run.

    Effects:
        pure: builds the adapter; nothing is sent until a port method is called.
    Repeat:
        safe: the adapter holds no connection or state.
    Loops:
        none
    Concurrency:
        free
    Raises:
        ValueError: the base URL is not an http(s) base URL, or the timeout is not positive.
    """
    return (
        Pipe
            .get(initial)
                .validate_url(schemes=frozenset({"http", "https"}))
                    .bind_json()
                        .materialize()
    )
