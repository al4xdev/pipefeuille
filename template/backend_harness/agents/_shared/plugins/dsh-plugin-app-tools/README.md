# dsh-plugin-app-tools

Which opt-in tools an agent gets, and the reader of `agents/<name>/agent.yml`. A library, not a plugin: no `apply`, no profile entry. The Dockerfile moves it into `/opt/dsh/node_modules` with the other plugins, so it is imported by package name (`dsh-plugin-app-tools`, `dsh-plugin-app-tools/agent`).

It is the one place a tool name is known and checked, and the one place (on the image's side) `agent.yml` is parsed. Its users:

| User | What it uses |
|---|---|
| `app-profiles.mjs` (`runtime/bin/`, image build) | `readAgent`, `pluginOf`: which shared plugins go into each agent's profile `app_<name>`; a bad `agent.yml` fails the build |
| `app-agent` (`runtime/bin/app-agent.sh`) | `cli.js <agents/<name>/agent.yml>`: prints the `APP_TOOLS` value, and `cli.js <agent.yml> limits` the `APP_LIMITS` value (the `limits` as JSON, for `dsh-plugin-app-limits`), or exits 2 with why, which stops the run |
| `dsh-plugin-app-fs` (and any other shared plugin) | `selectTools(process.env.APP_TOOLS)`, the second check, failing closed (no tools at all); `app-fs` takes its own names from `toolsOf` |
| `backend_harness/tests/context.mjs` | `readAgent`, to set `APP_TOOLS` the way `app-agent` does |

## `agent.yml`

`agents/<name>/agent.yml`, outside `workspace/`, so the model never sees it; every agent has one. The schema is in `agent.js`'s header: a `description`, the `limits` (`max_run_seconds` and `max_tokens` enforced in the run by `runtime/plugins/dsh-plugin-app-limits`, `max_attempts` by the server's queue), and the `tools`: `shared` names opt-in tools of `agents/_shared/plugins`, `own` gives the Effects and Repeat of each tool the agent's own plugins register; and the optional `model` (`name`, `reasoning`), which `runtime/bin/app-profiles.mjs` writes into `agent-default-model` of the agent's own profile (absent: the `app` profile's default). Unknown and duplicate keys are errors. YAML is read with `js-yaml`, which dsh itself depends on (no install of ours). At image build `tools.shared` decides which shared plugins the agent's profile inserts; `app-agent` reads it again on `run` and on `resume` (as `APP_TOOLS`, the plugins' defence), so a process cannot gain tools from its environment.

Here only the shape of `own` is checked: its values are the logic's closed E1 vocabulary (`Effects:`, `Repeat:`), defined once in the template's `tests/support/architecture.py`. Checking them, and holding every `own` entry to the tools the agent's context capture shows, is the logic side's job (Python gates over `agent.yml`, a later addition of the template; seam described in `backend_harness/README.md`).

## Where the names come from

Not from this package. Each shared plugin declares the tools it registers in its own `package.json`:

```json
"harness": { "tools": ["read", "write", "edit", "list", "trash", "apply_patch"] }
```

At import, this module reads the `package.json` of its sibling `dsh-plugin-*` packages (`agents/_shared/plugins/` in the repo, `/opt/dsh/node_modules/` in the image) and builds `KNOWN` from them, plugin by plugin in package name order. A malformed declaration, an empty list, or a name declared by two plugins throws at import, so the image build (`app-profiles.mjs`) fails. An agent's own plugin (`agents/<name>/plugins/`) declares no `harness.tools`: it is inserted into its agent's profile whole.

Today: `read`, `write`, `edit`, `list`, `trash`, `apply_patch` (`dsh-plugin-app-fs`). `edit` and `apply_patch` need `read`: they change a file from what the model read.

Adding an opt-in tool: declare it in its plugin's `package.json` (and the plugin reads `selectTools`), then run `backend_harness/tests/test.sh` and `backend_harness/tests/context.sh --build --check`.

## Exports

- `KNOWN`: every declared name.
- `toolsOf(plugin)`: the names one shared plugin declares (`[]` for any other package).
- `pluginOf(tool)`: the shared plugin that registers a name (`undefined` if unknown).
- `checkTools(names)`: `{ tools: Set }`, or `{ tools: empty Set, error }` for an unknown name or a missing `read`.
- `selectTools(value)`: `checkTools` over a comma-separated `APP_TOOLS`.
- `agent.js`: `readAgent(file)` / `parseAgent(text)`: `{ agent: { description, limits, shared: Set, own: [names], model: { name, reasoning } | null } }` or `{ error }`; `agentProblems(doc)`, the shape check.

## Model context

Nothing. It only decides which tools the other plugins register.

## Files

- `index.js`: the declarations scan and the checks (node only: the opt-in plugins load it).
- `agent.js`: the `agent.yml` reader.
- `cli.js`: `app-agent`'s check of an `agent.yml` (`APP_TOOLS`, or `APP_LIMITS` with `limits`).
- `package.json`: private ESM package `dsh-plugin-app-tools`, exports `.` and `./agent`.
