# dsh-plugin-app-fs

Opt-in file tools confined to the agent process's workspace, `/tmp/app-work/<tenant>/<agent_name>/<process_id>/`. Loaded only through the profile of an agent whose `agent.yml` lists one of them in `tools.shared` (`app_<name>`, generated at image build by `runtime/bin/app-profiles.mjs`: entry `id: app-fs`, `name: dsh-plugin-app-fs`, no config). Plugin name `app-fs`, injects `tools` and `systemPrompt`. It also owns the workspace fence, exported as `dsh-plugin-app-fs/workspace` for `dsh-plugin-app-sql`.

Its tool names are declared in `package.json` (`"app": {"tools": [...]}`), the list `dsh-plugin-app-tools` reads; adding a tool here means adding it there.

**Opt-in**: the image build inserts this plugin only into the profiles of agents that list one of its tools. `app-agent` checks `agents/<name>/agent.yml` with `dsh-plugin-app-tools` and exports `APP_TOOLS` (comma-separated), on `run` and `resume`. This plugin checks it again with the same module (defence) and fails closed: an unknown name, or `edit`/`apply_patch` without `read`, gives no tool at all and one stderr line `{"severity":"ERROR","component":"app-fs","event":"bad_tools",…}`. No file tool selected → the plugin registers nothing.

**Fence** (`workspace.js`), applied to every call:
- The session cwd must be exactly `/tmp/app-work/<tenant>/<agent>/<uuid>`, not reached through a link, with `<tenant>` equal to `APP_TENANT_ID`; otherwise every tool fails with `APP_FS_NO_WORKSPACE`.
- Paths are relative to the workspace; a path outside it reads as "not found". Reads may follow the template symlinks into `/opt/app/agents/<agent>/workspace/` (read-only); changes refuse any symlink component (`APP_FS_READ_ONLY`).
- `.dumps/`, `.dumps/.trash/` and `.dumps/.patch/` cannot be changed directly (`APP_FS_PROTECTED`).
- Limits: 16 MiB per file, 64 MiB and 10,000 entries per workspace (`APP_FS_QUOTA`), 4096-byte paths, 255-byte names.
- Writes go to a temp file and `rename`; error messages are scrubbed of absolute paths (tenant id).
- Read-before-change: `write` over an existing file needs the whole file read at its current version; `edit`/`apply_patch` need the touched lines read (`APP_FS_NOT_OBSERVED`, `APP_FS_STALE`). Observations are in memory, per process.

## Tools

Each is registered only if listed in `APP_TOOLS`; all return text.

| Tool | Parameters | Returns / behaviour |
|---|---|---|
| `read` | `file_path` string req.; `offset` number (1-based, default 1); `limit` number (default and max 2000) | Line-numbered window in a `<path>/<type>/<content>` envelope; lines cut at 2000 chars, output capped at 50 KiB with a continue hint. UTF-8 text only (`APP_FS_BINARY`), directories refused. Concurrency-safe. |
| `write` | `file_path` req.; `content` string req. | Creates or replaces the file, creating missing folders. Returns `Created file` / `Updated file`. |
| `edit` | `file_path` req.; `old_string` req. (non-empty); `new_string` req.; `replace_all` boolean (default false) | Literal replacement; refuses no match (`APP_FS_NO_MATCH`) or several without `replace_all` (`APP_FS_AMBIGUOUS_EDIT`). |
| `list` | `path` (default workspace); `depth` (default 1, max 8); `limit` (default 200, max 1000); `hidden` (default true) | Folders first (with `/`), then files; output capped at 64 KiB; follows a link only into a readable target. Concurrency-safe. |
| `trash` | `paths` string array req. (1–100, no globs) | Moves each path (a link as a link) into `.dumps/.trash/<timestamp>-<rand>-<name>`; JSON `{atomic:false, results:[{path,status:moved|not_moved,recovery|error}]}`. No permanent delete. |
| `apply_patch` | `patch` string req. (Codex format: Add/Delete/Update File, `*** Move to:`, exact context, `@@` anchors) | Checks every operation and the quota first; a thrown error means no file changed. Then applies in order, not atomic across files: backups and a `manifest.json` receipt go to `.dumps/.patch/<id>/`, deletes and moves go through trash. Returns the receipt JSON with per-file `state` (`changed`/`unchanged`/`partial`/`uncertain`). |
| `apply_patch_undo` | `manifest` string req. | Registered with `apply_patch`. Undoes only receipts made by this process; refuses to overwrite files changed after the patch. Returns the receipt with per-file `undo.state` (`restored`/`not_restored`). |

## Model context

When at least one file tool is selected: the tool descriptions above, and one system-prompt section `tool:app-fs` (order `TOOL_READ`) built from the selection by `guidance()` in `tools.js` (workspace-only paths; read before changing; scratch in `.dumps/`; trash semantics; with a tool that changes files, "Your answer is your final message, not a file."). An agent whose `tools.shared` lists none of them gets nothing from this plugin. Changing any description or the guidance changes the model context: run `backend_harness/tests/context.sh --build --check` (the `app.summarizer` baseline covers `read`, the one the example agent uses).

## Files

- `index.js`: reads `APP_TOOLS` (`selectTools`, and its own names via `toolsOf` from `dsh-plugin-app-tools`), adds the prompt section, registers the tools, scrubs errors.
- `tools.js`: `guidance`, the system-prompt text for the selected tools.
- `workspace.js`: the fence: process ids from the cwd, path resolution, quota, scrubbing, atomic write. Exported as `dsh-plugin-app-fs/workspace`.
- `files.js`: `read`, `write`, `edit`, `list`, `trash`, and the read observations.
- `patch.js`: Codex patch parser, `apply_patch` and `apply_patch_undo`.
- `package.json`: private ESM package `dsh-plugin-app-fs`, exports `.` (`index.js`) and `./workspace`; `app.tools` declares its tool names.