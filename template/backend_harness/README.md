# backend_harness: the agent runtime layer

Agents run here as **separate processes** of the [dsh](https://www.npmjs.com/package/@deepseek-ai/dsh) agent runtime (pinned), one process per run, each in its own workspace, dispatched over HTTP by a small server. It is the **runtime** of the agents; what an agent is *for* (when to dispatch it, what its output means, how it is admitted) belongs to the logic (`backend_logic`), through a port adapter (see [Seams](#seams-for-the-logic-side)).

Generic by construction: no cloud, no company, no tenant-as-product. Docker is the only platform it assumes.

## Which pipefeuille rules apply here, and which do not

This folder is **not** a `backend_logic` package tree and does not follow the four-file style. It is a runtime layer with its own rules, as an outbound resource is (guide §10: a client of an agent runtime is an adapter of a port; this folder is the runtime that adapter talks to).

| Rule of the template | Here | Why |
| --- | --- | --- |
| Four modules per package, `run.py` door, `Pipe`/`Container` vocabulary, `def run` docstrings and the architecture graph | **No** | The server is one HTTP module (`server/server.py`); the rest is dsh plugins (JavaScript), shell and YAML. There is no pipeline to read top-down. The agents become visible to the logic's graph through the logic-side adapter, not through this folder. |
| Python 3.15, `lazy` imports, `disallow_any_expr`, the template's `pyproject.toml` | **No** | The server is its own uv project: `server/pyproject.toml`, `server/uv.lock`, `server/.python-version` (3.14, which `compression.zstd` needs to read dsh's session logs), its own venv. It parses JSON from dsh and from requests with the standard library and pydantic, which carry `Any`; containing that would mean a boundary package per call for no reader's benefit. |
| Its own gates | **Yes, its own** | `server/pyproject.toml` configures ruff (same rule set as the template, line 120, py314) and strict mypy (without `disallow_any_expr`); pytest. `tests/test.sh` runs them, with the plugin tests and the rename self-test. |
| No secrets in code or logs; private data never a fixture; mocks by default; a real model call needs explicit authorization | **Yes** | Same reasons as everywhere (guide §11, §15). See [Real model runs](#real-model-runs). |
| Privacy before context; the model receives only what we put there | **Yes, enforced** | The profile disables everything the vendor runtime would add on its own, and `tests/context.sh --check` holds the exact context to reviewed baselines. |
| Comments for decisions and constraints, not for what the code says | **Yes** | |
| Dependency direction | **Yes**: `logic -> nothing`; `harness -> nothing` of ours; `services -> nothing` | The server imports neither `backend_logic` nor `http_adapter`. The logic reaches agents only through its harness adapter (a later wave), over HTTP. |

The template's root gates skip this tree for mypy only, and allow exactly one nested project file, `server/pyproject.toml` (see [Template gates](#template-gates)); ruff of the template root uses the server's own `[tool.ruff]` for `server/` (ruff picks the nearest config).

## Layout

```
backend_harness/
  README.md               this file
  Dockerfile              the image: dsh pinned, profiles, plugins, agents, server (context: this folder)
  Dockerfile.dockerignore what never enters the image (tests, venvs, docs)
  entrypoint.sh           the image's service manager: services/*/run.sh + the server, SIGTERM forwarded
  docker.sh               the developer's one script: build, serve [--pg], agent, run, config, shell
  rename-prefix.sh        rename the `app` prefix (FILL-IN) everywhere, with a self-test
  runtime/                the platform layer every agent inherits
    profiles/app/         base dsh profile `app`: no dsh tools, no vendor text, no side calls, no telemetry
    bin/app-agent.sh      one agent process: per-process workspace, `run` / `resume`, id checks
    bin/app-profiles.mjs  image build: one profile `app_<agent>` per agent (base + that agent's plugins)
    plugins/              dsh-plugin-app-limits (time/token limits), dsh-plugin-app-recovery (one retry, unexpected errors)
  agents/
    _shared/plugins/      opt-in plugins agents pick in agent.yml: dsh-plugin-app-tools (agent.yml schema + CLI, a library),
                          dsh-plugin-app-fs (file tools fenced to the workspace)
    summarizer/           EXAMPLE agent (notes domain): agent.yml, workspace/{AGENTS.md,style.md},
                          plugins/dsh-plugin-app-summarizer (finalize_summary)
  server/                 the harness server, its own uv project (Python 3.14)
    server.py             POST /dispatch, POST /status; memory or Postgres queue; usage; JSON logs
    tests/                its pytest (Postgres tests need APP_TEST_PG)
  services/               side processes of the image: the mechanism only, none shipped (services/README.md)
  tests/                  the harness's own offline gates
    test.sh               plugin/runner/profile tests in the image + server gates + rename self-test
    context.sh            the controlled-context gate (capture / --check / --update)
    context.mjs           the capture, run inside the image
    context-selftest.sh   proves the context gate fails on each of its four conditions
    denylist.txt          phrases that must never reach the model
    baseline/             the reviewed model context, one file per scenario
    e2e.sh                end to end: /dispatch -> app-agent -> dsh -> /status completed, offline
    e2e/                  TEST ONLY: the offline model stand-in and its derived image
    agents/, runtime/     *.test.mjs, mirroring the paths of what they test
```

## The prefix `app` (FILL-IN)

Every harness name carries one prefix, `app`, which a new project renames once: the profile `app`, the generated profiles `app_<agent>`, the runner `app-agent`, the plugins `dsh-plugin-app-*` (ids `app-*`), the environment `APP_*`, the paths `/opt/app` and `/tmp/app-work`, the image `app-harness`, the schema `app_harness`. It is always a token (never next to a letter or digit), so one command renames it, names and contents:

```fish
backend_harness/rename-prefix.sh myproj   # then: docker.sh build, tests/test.sh, context.sh --update with the owner's OK
```

`rename-prefix.sh --self-test` (run by `tests/test.sh`) renames a scratch copy and fails if any token survives, so a new name that breaks the token form is caught. dsh's own package `dsh-app-boot` is the one exception it keeps.

## Pinned dsh, plugins in the repo

- dsh is pinned in the `Dockerfile` (`ARG DSH_VERSION=0.2.0-rc.2`). **Never unpin it or install `latest`**: an upstream release can rename profile entry ids or the `dsh-llm` API our plugins import, and break the runtime without a change of ours. To upgrade: bump `DSH_VERSION`, check `./docker.sh config`, run `tests/test.sh` and `tests/context.sh --build --check`.
- **Every plugin outside the pinned dsh release lives in this folder** (`runtime/plugins/`, `agents/_shared/plugins/`, `agents/<name>/plugins/`), ours and forks alike. The image never installs a plugin from npm or from someone's machine.
- Don't add third-party resilience plugins that write their own text into the model context.

## The model context is controlled

The model receives only what we put there: no vendor identity, no coding persona, no runtime-context snapshot, no plan mode, no side model calls (session titles), no tools we did not add (`runtime/profiles/app/cordis.patch.yml`). After any change to the profile, a plugin, an agent's `agent.yml`, `workspace/` or plugins, the `Dockerfile` or `DSH_VERSION`, run:

```fish
backend_harness/tests/context.sh --build --check
```

It captures offline (`docker run --network none`; an `llm/stream` middleware answers before any adapter, so no provider is called) the first model request of a fresh agent in these scenarios: `app` (base profile), `app.recovery` (the request after a simulated `PROVIDER_TERMINATED`, carrying app-recovery's notice), `app.limit` (the request after a run passed its time limit, carrying app-limits' notice), and one `app.<agent>` per agent (its `AGENTS.md`, its tools, under its own profile). It fails on:

- **a dead entry** (`did not activate`): fix the entry; a capture of a half-booted runtime proves nothing;
- **a denylisted phrase** (`tests/denylist.txt`) in message text, a tool description or a tool schema: fix it at its source; never remove a denylist line to pass;
- **a baseline diff** (`tests/baseline/*.txt`): the model now gets different context. Show the owner the diff and where it comes from; accept it with `--update` **only after the owner says yes**, and commit the baseline with the change that caused it;
- **a stale baseline** (no scenario captures it any more): remove it with the change that removed its agent.

`tests/context-selftest.sh` proves each of the four failures (tampered baselines, a ghost baseline, a denylist naming the probe, a derived image whose plugin throws at boot).

The captures follow the headless runner exactly (route and reasoning effort from `agent-default-model`), so the `options` line is what a real run sends. The two notices are the only texts the harness adds to the context on its own.

**Initial baselines**: the four baselines in `tests/baseline/` were written by the wave that created this folder (no previous baseline existed); they are the reference from now on.

## Provider and real model runs

The profile keeps dsh's **built-in** provider as the default route (`deepseek-official` / `deepseek-flash`, entry `llm-deepseek`, credential `DEEPSEEK_API_KEY`, reasoning `low`). An agent may set another model of the same route in its `agent.yml` (`model: {name, reasoning}`). A project that needs another provider adds its adapter plugin to `runtime/plugins/` and moves `agent-default-model` to it.

Privacy before context, also on the wire: the profile disables `session-telemetry-otel` (session events to the vendor's collector), `session-log-deepseek` (the whole session log attached to each official-API request) and `plugin-package-inventory-deepseek` (the loaded package list attached to each request), and `session-title-llm` (a second model call). Known and left as dsh ships it: each official-API request carries dsh's anonymous per-installation id header (`x-deepseek-harness-user-id`); a project that must not send it needs a provider entry of its own.

**Real model runs.** Nothing in the tests, captures or e2e calls a provider. A real run needs both:

1. a credential: `DEEPSEEK_API_KEY` in your environment, passed into the container only with `./docker.sh --model-key serve` (by name, never on a command line); and
2. **the owner's explicit written authorization** in the project's `AGENTS.md` ("Data, secrets and authorizations"): which model, until when, for what. A credential being present is not authorization.

Without the key, every model request fails with `MISSING_CREDENTIAL` before any network call, and the run ends `failed`.

### Request failures, by error code

- **Transient** (`EMPTY_RESPONSE`, `RATE_LIMIT`, `SERVER`, `TIMEOUT`, `TRANSPORT`): dsh's built-in `llm-retry`, driven by the `retryPolicy` written out on `llm-deepseek` in the profile, the only list of transient codes. Nothing reaches the model.
- **Permanent** (auth, quota, context window, config, credential, a history the adapter cannot serialize): no retry; the turn fails.
- **Unexpected** (everything else, e.g. `PROVIDER_TERMINATED`, `MALFORMED_RESPONSE`): `dsh-plugin-app-recovery` retries once per turn after a fixed notice to the model, guarded by the `app.recovery` baseline. It also writes a **mock** JSON log line to stderr for every request error, a placeholder until real logging is designed.
- **Limits**: `dsh-plugin-app-limits` sends one notice at 100% of `max_run_seconds` or `max_tokens` and exits **75** (`LIMIT_EXCEEDED`, a final failure) at 125%; guarded by the `app.limit` baseline.

## Agents: `agent.yml`

Each agent is a folder `agents/<name>/` (name `^[A-Za-z0-9][A-Za-z0-9_]*$`, no `-`):

- `agent.yml` (outside `workspace/`, so the model never sees it): `description` (one or two sentences), `limits` (`max_run_seconds`, `max_tokens`: enforced in the run; `max_attempts`: the Postgres queue's reruns), `tools.shared` (opt-in tools of `agents/_shared/plugins`), `tools.own` (every tool its own plugins register, with the logic's E1 `effects` and `repeat`), optional `model`. Schema and the one parser: `agents/_shared/plugins/dsh-plugin-app-tools/agent.js`; a bad file fails the image build.
- `workspace/`: the read-only template every run's workspace links to; its `AGENTS.md` is the agent's instructions.
- `plugins/` (optional): its own dsh plugins, inserted only into its profile `app_<name>`. A tool that ends the run is declared in the plugin's `package.json` (`"harness": {"ends_run": [...]}`) and writes the run's output itself (one JSON line on stdout), as `finalize_summary` does.

Adding an agent: the folder above, then `tests/test.sh --build`, `tests/context.sh --check` (fails: no baseline yet), review the capture with the owner, `--update`.

## The server

`server/server.py` (FastAPI, uvicorn; `python server.py`), on `APP_HARNESS_HOST:APP_HARNESS_PORT` (default `127.0.0.1:8081`, loopback):

- `POST /dispatch {agent_name, tenant_id, input}` → `202 {status: "queued", process_id}`. Queues one `app-agent run <agent> <process_id> <input as JSON>`; at most `CAP` (20) run at once. `tenant_id` is trusted from the caller (backend to backend) and only separates workspaces and visibility; the model sees just `input`.
- `POST /status {tenant_id, process_id}` → `{status, process_id, output, reason, usage?}`; `status` is `queued | running | completed | failed`; `output` is the process's stdout once it ended; `reason` is `LIMIT_EXCEEDED`, `START_FAILED`, `ATTEMPTS_EXHAUSTED`, `RERUN_REFUSED` or null; `usage` (tokens summed from the run's dsh session log) is absent when unknown. Another tenant's process answers 404 like a missing one.
- Exit codes: 0 completed; 75 failed `LIMIT_EXCEEDED` (never rerun); any other failed.
- Queue: in memory by default (lost on restart, nothing rerun). With `APP_PG_DSN` (a libpq connection string), the table `app_harness.processes`, shared by instances: heartbeats, a reaper that requeues dead runs up to the agent's `max_attempts`, fenced writes. TLS, when a real database needs it, goes in the connection string.
- Logs: one JSON object per line with `severity` and `message`. An agent's stderr goes to `/tmp/app-work/<tenant>/<process_id>.err`; only its **structured** lines (JSON with `severity` and `component`: the plugins') are relayed to the server's log, with the `process_id`, never plain text (it carries the model's reasoning).

| Variable | Set by | Meaning |
| --- | --- | --- |
| `DSH_VERSION` | `Dockerfile` `ARG` | `0.2.0-rc.2`, pinned |
| `DSH_HOME` | `Dockerfile` | `/home/node/.dsh`: profiles and session logs |
| `APP_HARNESS_HOST`, `APP_HARNESS_PORT` | you / `docker.sh` | where the server listens (default `127.0.0.1`, `8081`) |
| `APP_PG_DSN` | `docker.sh --pg` | set = Postgres queue; unset or empty = memory |
| `APP_TENANT_ID` | the server, per run; `docker.sh` (`local`) | `^[A-Za-z0-9_-]+$`, at most 64: a workspace path segment |
| `APP_LIMITS`, `APP_TOOLS` | `app-agent`, per run | the agent's limits and shared tools from `agent.yml`, read by the plugins |
| `DEEPSEEK_API_KEY` | `docker.sh --model-key` only | the built-in provider's credential ([Real model runs](#real-model-runs)) |
| `APP_TEST_PG` | you, for `server/tests/test_pg_queue.py` | a disposable database for the Postgres tests |

## Running it

```fish
backend_harness/docker.sh                    # build, serve on http://127.0.0.1:8081 (memory queue, no model key)
backend_harness/docker.sh --pg               # same, with the Postgres container app-pg-local (plain TCP, local network)
backend_harness/docker.sh config             # the composed profile `app`
backend_harness/tests/test.sh                # plugin, runner and profile tests in the image; server gates; rename self-test
backend_harness/tests/context.sh --check     # the controlled-context gate
backend_harness/tests/context-selftest.sh    # the gate fails on each condition
backend_harness/tests/e2e.sh                 # /dispatch summarizer -> /status completed, --network none
backend_harness/tests/e2e.sh --pg            # the same on the Postgres queue (internal docker network)
```

`docker.sh serve` publishes the server on the host's loopback only (inside the container it listens on all interfaces so the port can be published).

## Services

`services/<name>/run.sh` is a side process of the image, discovered by `services/install.sh` (build) and `entrypoint.sh` (run); `services -> nothing`. The template ships the mechanism and no service: `services/README.md`.

## Seams for the logic side

Left for the wave that connects the logic (nothing here imports it):

- **Port adapter**: `backend_logic/_shared/task/harness/` will call `POST /dispatch` and `POST /status` (contracts above; `output` is the finalize tool's JSON line, to be decoded by the logic's strict JSON and admitted as a proposal). Its agent table maps a logic use case to an `agent_name` of `agents/`.
- **HTTP routes**: `http_adapter` forwards to the logic only; it reaches the harness through the logic's adapter. In the image, the HTTP application joins `entrypoint.sh` at the marked seam (started once the harness listens), becomes the published server, and the harness goes back to loopback only.
- **Architecture graph**: an `agent` node per `agents/<name>/agent.yml` (`description`, `tools.own` with E1 `effects`/`repeat`), read by the logic-side tool with its own parser.
- **Python gates over `agent.yml`**: E1 values of `tools.own`, every `own` entry equal to the tools the agent's capture shows (`tests/baseline/app.<agent>.txt`), every `ends_run` tool declared.

## Template gates

The template's root gates and this folder meet in two places, which need one narrow change of the root configuration (owner's, pipefeuille RUNBOOK task C): `pyproject.toml` `[tool.mypy] exclude` gains `"^backend_harness/"`, and `tests/gates/test_config.py` allows exactly `backend_harness/server/pyproject.toml` as a second project file and that one exclude, with a self-test of the scanner. Without it, `mypy .` checks the server under the template's 3.15/`disallow_any_expr` settings (274 errors) and `test_pyproject_is_the_only_tool_configuration` fails. Ruff and pytest need nothing: ruff uses the server's own `[tool.ruff]`, and the root pytest collects only `tests/`. A service with its own `pyproject.toml` would need the same kind of exception.

## Provenance

Backported from a production project's harness, generalized: the base profile, `app-agent`, the per-agent profile generator, the limits and recovery plugins, the `agent.yml` reader, the fenced file tools, the server (dispatch, status, memory and Postgres queues, usage, stderr relay, JSON logs), the entrypoint's service manager, `docker.sh`, and the context gate with its denylist. Not brought: its cloud launcher and job mode, its secret-bundle and mTLS database format, its environment and sandbox namespaces, its cloud logging trace fields, its provider adapter and credential plumbing (replaced by dsh's built-in provider), its cloud storage sync service, a DuckDB SQL tool (a second Python project inside the plugins; a project that needs it backports it with its own gate exception), its domain agents, and its Python `agent.yml` gate (the logic side's, later).
