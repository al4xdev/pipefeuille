"""The process entrypoint of the HTTP application: `python -m http_adapter.serve`.

The owner of the process configuration: it reads the environment once, here, and passes every
value explicitly (nothing below reads it). In the image (backend_harness/entrypoint.sh) it is
the public server, started once the harness server listens on loopback.

    APP_DATA_ROOT     where notes are stored (required)
    APP_HARNESS_URL   the harness server (default http://127.0.0.1:8081, its loopback)
    APP_HTTP_HOST     default 127.0.0.1; the image sets 0.0.0.0 so its port can be published
    APP_HTTP_PORT     default 8080
"""

lazy import os
lazy import sys
lazy from pathlib import Path

lazy import uvicorn

lazy from backend_logic._shared.agents.harness.contracts import OpenHarness

lazy from .application import create_app


def main() -> int:
    data_root = os.environ.get("APP_DATA_ROOT")
    if not data_root:
        print("serve: APP_DATA_ROOT is required", file=sys.stderr)
        return 2
    harness = OpenHarness(
        base_url=os.environ.get("APP_HARNESS_URL") or "http://127.0.0.1:8081",
        timeout_seconds=10.0,
    )
    app = create_app(data_root=Path(data_root), agents=harness)
    host = os.environ.get("APP_HTTP_HOST") or "127.0.0.1"
    port = int(os.environ.get("APP_HTTP_PORT") or "8080")
    uvicorn.run(app, host=host, port=port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
