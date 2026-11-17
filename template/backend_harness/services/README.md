# services/

Side processes of the image (Docker has no systemd). **The template ships none**: the folder carries only the mechanism, so a project adds a service without touching the Dockerfile or the entrypoint.

- A service is any folder `services/<name>/` with a `run.sh`. Nothing else registers it.
- `run.sh` maps the image's environment to the service's own config and `exec`s the service in the foreground.
- At build, `install.sh` (this folder) installs each one: a `pyproject.toml` gets its locked venv (`uv sync --frozen` on the exact interpreter of the service's `.python-version`), then the service's own `install.sh` runs if present.
- At run, `entrypoint.sh` starts every `services/*/run.sh` in name order next to the harness server, forwards SIGTERM, and gives services a bounded final pass after the server is gone.
- `services -> nothing`: a service imports neither the logic, the HTTP adapter nor the harness server.

Why the mechanism and no service: the source project's only generic-looking service (a session-log uploader) was tied to its cloud storage, so it did not come; an empty `services/` keeps the seam without shipping a process nobody asked for.

A service with its own `pyproject.toml` hits the same template gate as the harness server (`tests/gates/test_config.py::test_pyproject_is_the_only_tool_configuration`): it needs the same narrow exception (see `../README.md`, "Template gates").
