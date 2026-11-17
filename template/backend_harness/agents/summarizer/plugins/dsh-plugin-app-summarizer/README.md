# dsh-plugin-app-summarizer

The example agent `summarizer`'s own plugin (an EXAMPLE of the template's `notes` domain: it goes away with that domain). Inserted only into the agent's profile `app_summarizer` by `runtime/bin/app-profiles.mjs` (every folder of `agents/summarizer/plugins/`). Plugin name `app-summarizer`, injects `tools`.

## Tools

| Tool | Parameters | Behaviour |
|---|---|---|
| `finalize_summary` | `summary` string, required | Checks the summary (`summary.js`: non-empty, at most 600 characters and 3 sentences, plain prose). With problems it throws, listing them, and hands nothing over (the model may call again). Accepted: writes `{"summary": "<text>"}` as one JSON line on stdout, silences stdout after it, and concludes the turn (`exec.concludeTurn()`), so headless dsh exits 0 and the harness server stores that line as the run's output. A second call after an accepted one is rejected. |

`package.json` declares `"harness": {"ends_run": ["finalize_summary"]}`; `app-profiles.mjs` holds that to `tools.own` of `agents/summarizer/agent.yml`, which gives the tool's Effects and Repeat.

## Model context

The tool's description and schema (above). Guarded by the `app.summarizer` baseline of `backend_harness/tests/context.sh`.

## Files

- `index.js`: the tool.
- `summary.js`: `problemsOf`, the admission rules (mirror `workspace/style.md`).
- `package.json`: private ESM package, exports `.` and `./summary`.

Tests: `backend_harness/tests/agents/summarizer/plugins/dsh-plugin-app-summarizer/summary.test.mjs`, run by `backend_harness/tests/test.sh`.
