# The backend image: dsh (pinned) + our profile and plugins + the harness server,
# and the logic's HTTP application (backend_logic + http_adapter), the public server.
# Build context: this folder (backend_harness/), plus the named context `logic`, the
# template root (`./docker.sh build` passes `--build-context logic=..`; only the paths
# copied below are read from it). The same image serves local runs and any container
# platform: nothing here depends on the developer's machine, and no credential is
# baked in.
FROM node:24-bookworm-slim

# The slim base has no CA bundle. Node carries its own, but uv's Python uses the
# system's (any HTTPS call from the server, or uv fetching Python at build).
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Pinned, never `latest` (README.md, "Pinned dsh"): profile ids in cordis.patch.yml
# and the dsh-llm API our plugins import are only valid for this release. Bump
# together with a `./docker.sh config` check and `tests/context.sh --build --check`.
ARG DSH_VERSION=0.2.0-rc.2

# A local prefix, not `npm install -g`: our plugins must sit in the SAME
# node_modules as dsh. They import @deepseek-ai/dsh-llm and schemastery from there,
# and ESM resolution ignores NODE_PATH, so a global install would leave them
# unresolvable (and a second copy of dsh-llm breaks LlmAdapter identity).
WORKDIR /opt/dsh
RUN npm init -y >/dev/null \
 && npm install --omit=dev "@deepseek-ai/dsh@${DSH_VERSION}" \
 && npm cache clean --force
ENV PATH=/opt/dsh/node_modules/.bin:$PATH

# The harness server (server/), with uv pinned like dsh. Its Python (exact, from
# server/.python-version) and its locked deps are installed at build time; nothing
# runs uv at runtime.
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /usr/local/bin/uv
ENV UV_PYTHON_INSTALL_DIR=/opt/python UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /opt/app/server
COPY --chmod=0644 server/pyproject.toml server/uv.lock server/.python-version ./
# --no-cache: with UV_LINK_MODE=copy the venv owns its files; a cache left in this
# layer would double every wheel.
RUN uv sync --frozen --no-dev --no-install-project --no-cache --python "$(tr -d '[:space:]' < .python-version)"
COPY --chmod=0644 server/server.py ./

# The logic's HTTP application: its own uv project (the template root's pyproject and
# lock, Python 3.15), installed like the server's. Only what it imports is copied: no
# tests, docs or the harness itself. PyYAML (through uvicorn[standard]) has no cp315
# wheel and builds from its sdist without the C extension, as on a developer machine.
WORKDIR /opt/app/web
COPY --from=logic --chmod=0644 pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --no-cache --python 3.15
COPY --from=logic --chmod=0755 backend_logic/ backend_logic/
COPY --from=logic --chmod=0755 http_adapter/ http_adapter/
RUN find /opt/app/web/backend_logic /opt/app/web/http_adapter -name __pycache__ -prune -exec rm -rf {} +

# Side services (services/<name>/run.sh, started by the entrypoint). Generic on
# purpose: adding a service never touches this file; services/install.sh finds
# and installs each one. The template ships none.
COPY --chmod=0755 services/ /opt/app/services/
RUN /opt/app/services/install.sh

# runtime/ is the platform layer every agent inherits: its profiles become the dsh
# home's profiles, its plugins are installed below.
ENV DSH_HOME=/home/node/.dsh
COPY --chown=node:node runtime/profiles/ /home/node/.dsh/profiles/

# Every plugin the runtime loads comes from this repo (runtime/plugins and
# agents/**/plugins), copied after the npm install so no later npm step can prune
# them. --chmod: COPY keeps the checkout's modes, and a 600 file is unreadable to
# the `node` user, which surfaces only as "failed to import" at boot.
COPY --chmod=0755 runtime/plugins/ /tmp/app-plugins/
# Agents are read-only templates (root-owned); app-agent symlinks one into a fresh
# per-process workspace; each declares itself in agents/<name>/agent.yml (beside
# workspace/, so the model never sees it). dsh has no per-agent plugins, so the
# build makes one profile per agent (app_<name>, runtime/bin/app-profiles.mjs) and
# app-agent runs that one: loading is the harness's job, never the plugin's.
# Plugin folder names must be unique across runtime/plugins and agents/**/plugins.
COPY --chmod=0755 agents/ /opt/app/agents/
COPY --chmod=0755 runtime/bin/app-agent.sh /usr/local/bin/app-agent
COPY --chmod=0755 runtime/bin/app-profiles.mjs /opt/app/bin/app-profiles.mjs
COPY --chmod=0755 entrypoint.sh /usr/local/bin/app-entrypoint
# Two places on purpose: dsh resolves plugin NAMES from $DSH_HOME/profiles/
# node_modules, while a plugin's own imports (@deepseek-ai/dsh-llm, dsh-plugin-
# app-tools) resolve from its real path. So the files live next to dsh in
# /opt/dsh/node_modules and the profile tree only gets symlinks. Unscoped package
# folders only. An agent's plugin folder is left as a symlink to its installed
# copy, so agents/<name>/plugins still lists them (app-profiles.mjs reads it and
# their package.json, and agent.yml with dsh's own js-yaml: a bad one fails the
# build). Then the per-agent profiles, node-owned like the base one (dsh rewrites a
# profile's cordis.yml on boot), and every agent's limits for the harness server
# (/opt/app/server/agents.json, root-owned: server.py AGENTS_FILE).
RUN mkdir -p "$DSH_HOME/profiles/node_modules" \
 && for dir in /tmp/app-plugins/*/ /opt/app/agents/*/plugins/*/; do \
      [ -d "$dir" ] || continue; \
      name="$(basename "$dir")"; \
      [ ! -e "/opt/dsh/node_modules/$name" ] || { echo "duplicate plugin $name" >&2; exit 1; }; \
      mv "$dir" "/opt/dsh/node_modules/$name"; \
      ln -s "/opt/dsh/node_modules/$name" "$DSH_HOME/profiles/node_modules/$name"; \
      case "$dir" in /opt/app/agents/*) ln -s "/opt/dsh/node_modules/$name" "${dir%/}" ;; esac; \
    done \
 && rm -rf /tmp/app-plugins \
 && node /opt/app/bin/app-profiles.mjs --agents-json /opt/app/server/agents.json /opt/app/agents "$DSH_HOME/profiles" \
 && chown -R node:node "$DSH_HOME/profiles" \
 && install -d -o node -g node /home/node/work

USER node
WORKDIR /home/node/work
# The harness server listens on 127.0.0.1:8081 (loopback: only what runs in this
# container reaches it, the HTTP application among them). The HTTP application is
# the public server, on 0.0.0.0:8080 so the port can be published (docker.sh serve
# publishes it on the host's loopback); its notes live in APP_DATA_ROOT, lost with
# the container unless a volume is mounted there.
ENV APP_DATA_ROOT=/home/node/data APP_HTTP_HOST=0.0.0.0 APP_HTTP_PORT=8080
RUN install -d -m 0700 /home/node/data
ENTRYPOINT ["/usr/local/bin/app-entrypoint"]
