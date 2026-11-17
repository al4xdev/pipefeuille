# tools/telemetry: `app-telemetry`, the developer's view of agent sessions

A **developer tool**: it reads the dsh session logs the agents of [`backend_harness/`](../../backend_harness/README.md) write (one per run: turns, model requests, tool calls, tokens, timings, errors) and never writes to them. **Product agents never get it**: it is not in the harness image, not in any `app_<agent>` profile and not in any `agent.yml`; the dsh plugin below goes only into the developer's own dsh profile.

It has two modes:

- a terminal UI for humans: the sessions list, then dsh-tui's Trajectory screen (vendored, [`VENDOR.md`](VENDOR.md));
- headless JSON for agents (the developer's coding agent), plus a local DuckDB cache of prepared feature tables, queried read-only.

Node 24 or later. `node_modules/` is installed by `npm ci` and ignored by git (`.gitignore` here); never commit it.

```fish
cd tools/telemetry; and npm ci
node bin/app-telemetry.js                        # TUI on the running harness container (--local, the default)
node bin/app-telemetry.js --dir ~/sessions       # a host copy (backend_harness/docker.sh SESSIONS=~/sessions)
node bin/app-telemetry.js --tenant_id acme sessions
```

Do not decode the session logs by hand: a `session.v4.jsonl.zstd` holds one zstd frame per append, and node's own decoders stop after the first (`src/decode.js`).

## Sources

| Flag | Reads | Needs |
|---|---|---|
| `--local` (default) | `/home/node/.dsh/sessions` of the container `app-harness-local` (`backend_harness/docker.sh serve`), copied out with `docker cp` into a temporary folder removed on exit | `docker` |
| `--dir PATH` | a host folder of dsh sessions: `backend_harness/docker.sh SESSIONS=PATH ...` mounts one, or `docker cp <container>:/home/node/.dsh/sessions PATH` copies one | nothing |

A session is identified only by its path: `--tmp-app-work-<tenant_id>-<agent_name>-<process_id>--/session-<uuid>/session.v4.jsonl.zstd`, the folder dsh names after the workspace `/tmp/app-work/<tenant>/<agent>/<process_id>` that `backend_harness/runtime/bin/app-agent.sh` creates (`src/paths.js`). Sessions of other cwds (a `docker.sh run`, a context capture) are not listed. `docker.sh agent run` uses a `--rm` container: pass `SESSIONS=dir` and read it with `--dir`.

## Filters

`--tenant_id`, `--agent_name`, `--process_id` and `--session_id` match by prefix (`session_id` with or without its `session-`).
`--date` takes `YYYY-MM-DD` or `FROM..TO` (either side may be open) and compares
in UTC against the session start. In the TUI, `/` edits the same filters as
`key:value` tokens, and a bare word matches any id. While you type, it suggests
the fields, then the values that field has among the loaded sessions, each with
the sessions it would leave: **↑↓** pick, **Tab** completes, **Enter** applies.

## Headless (agents)

Each command prints one JSON object per line on stdout. Running without a TTY is
headless too.

| Command | Output |
|---|---|
| `sessions` | the matching sessions: identity, `started_at`, `updated_at`, `bytes` |
| `trajectory SESSION_ID [--detail]` | the fold behind the Trajectory screen: totals, hotspots, rows (`--detail`: each row's input/output) |
| `sync` | reads the matching sessions and builds their feature tables in the cache (incremental: a session is decoded again only when its size changed; a filtered sync never drops the others) |
| `schema` | every table of the cache: row count, columns, types, meaning |
| `sql "QUERY" [--sync]` | queries the cache offline and read-only |

There is one cache per source: `~/.cache/app-telemetry/local.duckdb` (`--local`) or `~/.cache/app-telemetry/dir-<sha256 of the path, 8 hex>.duckdb` (`--dir`), or the file given with `--db`. The tables are `sessions`, `events`, `rows`, `hotspots`,
`tool_calls`, `model_calls` and `turns`. They hold the numbers the TUI shows, and
`schema` describes them. Use `json_extract_string(data, '$.path')` on JSON columns: DuckDB's
`->>` binds looser than `=` and `AND`.

```fish
node bin/app-telemetry.js sync
node bin/app-telemetry.js sql "SELECT agent_name, count(*), avg(span_ms) FROM sessions GROUP BY 1"
```

DuckDB is loaded only by `sync`, `sql` and `schema`.

### What a query may do

`query` in `src/db.js` is the one guard, used by `sql` and by the plugin:

- each query runs on a private copy of the cache, opened read-only (DuckDB lets a connection write its own WAL; only the copy could be touched), taken while the cache is held read-only so a running `sync` makes it fail cleanly;
- `enable_external_access = false` (no file read or write: `read_csv`, `read_text`, `glob`, `COPY ... TO`, `EXPORT DATABASE`, attaching a file), `autoinstall_known_extensions = false` and `autoload_known_extensions = false` (no extension downloaded or loaded by a query), then `lock_configuration = true`;
- every statement is prepared and checked before any runs: only `SELECT` and `EXPLAIN` statement types (so `WITH`, `FROM`-first, `SHOW`, `DESCRIBE`, `SUMMARIZE` pass; `INSERT`, `DELETE`, `CREATE`, `SET`, `RESET`, `PRAGMA`, `ATTACH`, `DETACH`, `USE`, `INSTALL`, `LOAD`, `CALL`, `CHECKPOINT` do not);
- then DuckDB's own parse tree of the query (`json_serialize_sql`) is searched for refused functions, however they are spelled (quoted, upper-cased, a comment before the parenthesis, in a subquery): the logging table functions `enable_logging`, `disable_logging`, `truncate_duckdb_logs` (they change the instance past `lock_configuration`, and a denied file sink can abort the process), and `query`/`query_table` (they run SQL given as text, which no check sees). A lone `EXPLAIN [ANALYZE]` is checked on the query it explains (`ANALYZE` runs it); a query whose tree cannot be read (an `EXPLAIN` after another statement) is refused, not run. Binding a statement has no effect, so this check sits after the types and before anything runs.

`test/refusals.js` is the list of refused queries by what they try (writes; file reads and writes; settings changes; other databases and extensions), run against `sql` (`test/db.test.js`) and the plugin (`test/plugin.test.js`), which also check the cache file is unchanged byte for byte and nothing was written.

## The dsh plugin for the developer's session: `dsh-plugin-app-telemetry-sql`

Two read-only tools for the developer's own dsh session (the coding agent working on this project), over the caches `sync` built:

- `telemetry_sql {query, cache?}`: one query through the guard above; JSON lines, cut at 200 rows or 60 000 characters with a final `{"truncated": true, ...}` line.
- `telemetry_schema {cache?}`: the caches present, then `schema`'s lines.

`cache` is a name (`local`, `dir-1a2b3c4d`), never a path: the tool opens only `<cache folder>/<name>.duckdb`. The plugin runs no `sync`: the developer runs it in a shell (`node bin/app-telemetry.js sync`), so the cache is what the developer chose to load.

Install, once per developer profile (never in `backend_harness/`):

1. `npm ci` in `tools/telemetry` (the plugin loads DuckDB from there).
2. Add to your profile's `~/.dsh/profiles/<profile>/cordis.patch.yml`, with the absolute path of this checkout:

   ```yaml
   - insert:
       - id: app-telemetry-sql
         name: /absolute/path/to/tools/telemetry/dsh-plugin-app-telemetry-sql/index.js
         config:            # optional; these are the defaults
           cache: local     # the cache a call reads when it names none
           maxRows: 200
           maxChars: 60000
   ```

   `config.cacheDir` (an absolute path; `~` is not expanded) replaces the cache folder, by default `$XDG_CACHE_HOME/app-telemetry` or `~/.cache/app-telemetry`, the one the command line writes.

3. Start a new dsh session on that profile; the tools are `telemetry_sql` and `telemetry_schema`.

The plugin takes `@deepseek-ai/dsh-tools` from the dsh that loads it (its own folder has no dsh), so it runs only inside a dsh session; importing it elsewhere fails with that message. It never imports `src/sources.js`, whose exit and signal handlers would bind the dsh process (`test/plugin.test.js`).

## Tests

```fish
npm test                  # everything below but the real-dsh run; no docker, no network
test/dsh-boot.sh          # the plugin inside a real dsh (the harness image's pinned one), offline
```

The fixtures in `test/fixtures/sessions/` are two real sessions of the template harness: the example agent `summarizer` under the offline stub model (`backend_harness/tests/e2e/`), one dispatched once (tenant `acme`), one dispatched and resumed (tenant `t-1_x`, two turns, with its `session.lock`). `test/dsh-boot.sh` runs a headless dsh in a throwaway `app-harness:local` container (`--network none`) whose profile `devsql` is the base profile `app` plus this plugin and a test-only scripted model (`test/dsh-boot/dsh-plugin-app-telemetry-probe`), then reads that session back with `app-telemetry` and checks the two reads answered and the five refusals came back as tool errors.

## The prefix `app`

Every name here carries the harness's renameable prefix as a token: the binary `app-telemetry`, the cache folder `app-telemetry`, the container `app-harness-local`, the workspace `/tmp/app-work`, the plugin `dsh-plugin-app-telemetry-sql` (id `app-telemetry-sql`). `backend_harness/rename-prefix.sh NEW` renames this folder together with the harness, and its `--self-test` checks both. The fixtures are compressed, so their recorded cwd keeps `app-work` after a rename; the tests accept either (a renamed copy's `npm test` passes: the header cwd then no longer matches, and the ids come from the folder name, which was renamed).

## Provenance

Backported from a production project's session viewer, generalized. Not brought: its cloud object-store source (listing and download, credential plumbing, the chunked mirror layout that came with it), its environment names, and its legacy path layout without `agent_name`. Vendored code and its edits: [`VENDOR.md`](VENDOR.md).
