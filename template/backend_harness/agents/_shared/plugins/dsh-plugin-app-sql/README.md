# dsh-plugin-app-sql

Opt-in `sql` tool: DuckDB queries over files of the agent process's workspace, each call in its own locked-down Python worker. Loaded only through the profile of an agent whose `agent.yml` lists `sql` in `tools.shared` (`app_<name>`, generated at image build by `runtime/bin/app-profiles.mjs`: entry `id: app-sql`, `name: dsh-plugin-app-sql`, no config). Plugin name `app-sql`, injects `tools` and `systemPrompt`. The name `sql` is declared in `package.json` (`"harness": {"tools": ["sql"]}`), the list `dsh-plugin-app-tools` reads. It imports the opt-in check from `dsh-plugin-app-tools` and the fence from `dsh-plugin-app-fs/workspace`, by package name: both resolve in `/opt/dsh/node_modules`, where the Dockerfile puts every plugin (the fence is a module import, so `app-fs` need not be inserted).

**No Python project of its own.** The worker runs on the harness server's venv (`/opt/app/server/.venv/bin/python`, `PYTHON` in `sql.js`): `duckdb==2.0.0` is one of `backend_harness/server/pyproject.toml`'s locked dependencies, so the runtime layer keeps one Python project (and the template's root gates one exception for it). `worker.py` is typed by the server's strict mypy and linted by the template root's ruff (`backend_harness/tests/test.sh`, step 2).

## Tools

### `sql`

Registered only if `APP_TOOLS` contains `sql` (from `agent.yml`, via `app-agent`; a defence on top of the profile); an invalid `APP_TOOLS` means no tool. Concurrency-safe; at most 4 workers run at once per process, the rest wait.

| Name | Type | Req. | Meaning |
|---|---|---|---|
| `query` | string | yes | DuckDB SQL, at most 100 KiB. Allowed statements: SELECT, EXPLAIN, PIVOT (MULTI), and CREATE/INSERT/UPDATE/DELETE/DROP on in-memory scratch tables. The last statement's result is returned. |
| `tables` | array of objects | no | Up to 16 files: `{path, …reader options}`. Each loads as a table named after the file without extension, other characters as `_`, leading digit prefixed `t_`, max 63 chars; two files mapping to the same (case-insensitive) name are refused. |
| `memory_mb` | integer | no | 64–1024, default 128. Threads: 1 below 256 MB, else 2. Spill to disk up to 2× this. |
| `timeout_s` | integer | no | 1–300, default 60. |
| `max_rows` | integer | no | 1–2000, default 200. |

Reader options (validated in `sql.js`, bound as `read_csv` parameters in `worker.py`, never as SQL text): `format` (`auto`/`csv`/`json`/`parquet`), `delimiter` (≤4 chars), `quote`, `escape`, `thousands` (1 char), `header`, `all_varchar` (boolean), `skip` (0–1,000,000), `decimal_separator` (`.`/`,`), `encoding` (`utf-8`/`utf-16`/`latin-1`), `dateformat`, `timestampformat`, `nullstr` (≤64 chars). With `format` auto the worker detects by content: `PAR1` magic → Parquet, leading `{`/`[` → JSON, else CSV sniffing. Options other than `format` apply only to CSV.

Returns: CSV (header + rows, `NULL` for nulls, cut at the last whole row under 50 KiB) followed by `(<shown> of <total> rows…)`.

How a call runs (`sql.js` → `worker.py`):
1. Each table path goes through the `app-fs` fence (`resolveRead`: workspace or read-only agent template); it must be a regular file.
2. A spill folder `/tmp/app-sql/<random>` (mode 700) is created outside the workspace, so the tenant id never shows in DuckDB's `allowed_directories`; it is removed after the call.
3. `python -I worker.py` starts with an empty environment, cwd the workspace, the request as JSON on stdin.
4. The worker opens each table's resolved file itself (`O_NOFOLLOW`, a regular file) and gives DuckDB only `/proc/self/fd/<n>`: DuckDB reads a path as a pattern (`*`, `?`, `[...]`, `{...}`, `**`), so a workspace file named `*` would otherwise load every entry beside it, past the fence. A name with those characters (`g[a-z].csv`) loads as itself. No compression is guessed from a name (there is none to read): a compressed file does not load.
5. The worker connects in memory with extension autoload/autoinstall, community extensions and persistent secrets off, loads the tables, then sets `enable_external_access = false` and `lock_configuration = true`, so the query reaches no file (except the spill folder) and no network.

Errors: argument checks; fence errors (`APP_FS_*`); `APP_SQL_TABLE_NAME`; `APP_SQL_ERROR` (DuckDB or refusal message, first line); `APP_SQL_STOPPED` (timeout, cancel, or stdout over 256 KiB; the worker is SIGKILLed); `APP_SQL_FAILED` (crash, e.g. OOM kill). Messages are scrubbed of host paths. On a crash one JSON line goes to stderr: `{"severity":"ERROR","component":"app-sql","event":"worker_failed",…}`.

## Model context

When `sql` is selected: the tool and parameter descriptions in `index.js`, and one system-prompt section `tool:app-sql` (order `TOOL_READ`, the `GUIDANCE` text). Agents without `sql` get nothing. No example agent picks it, so no baseline covers its text yet: the first agent that does gets an `app.<agent>` capture, reviewed by the owner before `--update` (`backend_harness/README.md`, "The model context is controlled").

## Files

- `index.js`: opt-in check, prompt section, tool definition and parameter descriptions.
- `sql.js`: limits, reader-option validation, table resolution through the fence, worker spawn and slots.
- `worker.py`: DuckDB worker: format detection, table load, lock-down, statement allowlist, CSV output.
- `package.json`: private ESM package `dsh-plugin-app-sql`, exports `.` and `./sql`.

Tests: `backend_harness/tests/agents/_shared/plugins/dsh-plugin-app-sql/sql.test.mjs` (in the image, `--network none`).
