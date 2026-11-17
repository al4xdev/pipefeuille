"""The process entrypoint of the HTTP application, a factory the server process calls once:

    uvicorn --factory http_adapter.serve:app_from_env --host HOST --port PORT

The owner of the process configuration: it reads the environment once, here, and passes every
value explicitly (nothing below reads it). The server library is never imported by the code:
`uvicorn` loads applications from "module:attr" strings, which the boundaries gate refuses
(template-decisions D9), so it runs only as the command above. In the image
(backend_harness/entrypoint.sh) it is the public server, started once the harness server
listens on loopback; host and port belong to that command line (APP_HTTP_HOST and
APP_HTTP_PORT there; the image sets 0.0.0.0:8080 so its port can be published).

    APP_DATA_ROOT     where notes are stored (required)
    APP_HARNESS_URL   the harness server (default http://127.0.0.1:8081, its loopback)
"""

lazy import os
lazy from pathlib import Path

lazy from fastapi import FastAPI

lazy from backend_logic._shared.agents.harness.contracts import OpenHarness

lazy from .application import create_app


def app_from_env() -> FastAPI:
    data_root = os.environ.get("APP_DATA_ROOT")
    if not data_root:
        raise SystemExit("serve: APP_DATA_ROOT is required")
    harness = OpenHarness(
        base_url=os.environ.get("APP_HARNESS_URL") or "http://127.0.0.1:8081",
        timeout_seconds=10.0,
    )
    return create_app(data_root=Path(data_root), agents=harness)
