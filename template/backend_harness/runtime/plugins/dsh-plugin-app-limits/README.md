# dsh-plugin-app-limits

Enforces an agent's declared `max_run_seconds` and `max_tokens` (`agents/<name>/agent.yml`, `limits`; `null` = no limit) from inside the agent process: no external ticker, nothing to run beside it. Loaded by every agent through the `app` profile (`cordis.patch.yml`, entry `id: app-limits`, `name: dsh-plugin-app-limits`, right after `app-recovery`). Plugin name: `app-limits`. `max_attempts` is not enforced here: it is the queue's (the harness server).

## Input: `APP_LIMITS`

`app-agent` (`runtime/bin/app-agent.sh`) exports `APP_LIMITS` on `run` and `resume`: the JSON of the agent's `limits`, printed by `dsh-plugin-app-tools/cli.js <agent.yml> limits` from the one `agent.yml` parser (`dsh-plugin-app-tools/agent.js`), e.g. `{"max_run_seconds":600,"max_tokens":null,"max_attempts":3}`. The plugin reads `max_run_seconds` and `max_tokens` (each a positive integer or `null`) and ignores the rest.

- Absent or empty: no limits, the plugin does nothing (dsh run by hand, `./docker.sh` dsh modes, the bare-profile context capture).
- Both `null`: nothing is watched (no timer, no listener).
- Malformed: one `bad-limits` line on stderr and exit 2 at boot. `app-agent` prints it from a checked `agent.yml`, so this is a broken launcher; booting without the limits would fail open.

## What it does

A run is one process (`app-agent run` or `resume`): the clock starts when the plugin is applied at boot, the token count at zero. Nothing is persisted, so a resumed process starts again from zero.

**Resume restarts the budget** (time and tokens from zero); nothing calls `app-agent resume` today (the server reruns a requeued task from scratch).

| When | What |
|---|---|
| a limit reaches **100%** (≥ the value) | **once** per process, whichever limit comes first: a `WARNING` `limit-reached` line on stderr and the notice below to the model. Only a model response **still streaming with no tool call** is interrupted (`agent.cancel({ kind: 'hook' })`), and the notice opens the next turn (`followup`). In every other case (the response has a tool call, its tools are running, between steps, idle, or the response that crossed the token limit just ended) the notice waits for the next step boundary (`inject`): nothing is cancelled or woken, so the notice never aborts the delivery it asks for (a `finalize_*` tool, a write, a query). Counting goes on. |
| a limit reaches **125%** (`value × 4 ≥ max × 5`) | one `ERROR` `limit-exceeded` line on stderr, a best-effort flush of the session log (`ctx.sessionPersistence.flush()`; the jsonl backend batches writes for 200 ms), then **exit 75**: after the flush, its failure, or `FLUSH_CAP_MS` (1 s), whichever comes first. Not cancelling first on purpose: dsh's headless runner would see an aborted turn and exit 1 before us. |

A response that jumps from under 100% to 125% or more stops the run with no notice.

Known, rare: a 125% stop that lands after a `finalize_*` tool printed its JSON but before dsh exits is still exit 75, so the server records the run as **failed**.

**Time**: one `setTimeout` (unref'd, so it never keeps a finished run alive) for the next threshold still ahead (100% until the notice, then 125%), its delay capped at `MAX_TIMER_MS` (2³¹−1 ms, setTimeout's largest; a farther threshold fires early and re-arms), re-armed from the clock, so a timer that fires early waits again.

**Tokens** (enforced: the pinned dsh `0.2.0-rc.2` gives plugins each response's usage): every `usage` chunk of `agent/assistant-stream`, one per model attempt (retries included), counted when the attempt's `end` frame arrives (the response is settled then, never cut in half). Count = `inputTokens + cacheReadTokens + cacheWriteTokens + outputTokens + reasoningTokens` of dsh's `TokenUsage` (uncached input, cached input, output, thinking). Not counted: model calls that do not stream to the agent (compaction's summary request).

Why `reasoningTokens` is added although dsh's contract makes it a subset of output: an adapter may report a model's thinking only in `reasoningTokens`, outside `outputTokens`; without it that thinking would not be counted at all. If an adapter does report reasoning **inside** `outputTokens` as the contract says, this double counts it: the run is cut earlier, never later, which is the safe side.

## Exit code 75: `LIMIT_EXCEEDED`

`LIMIT_EXCEEDED_EXIT = 75` in `index.js` is our contract with the harness server: a run that exits 75 was stopped by its own limit, a **final** failure, never requeued. 75 happens to be sysexits' `EX_TEMPFAIL`; that meaning is **not** intended (nothing is temporary here). It only had to be a code that neither node, dsh nor `app-agent` (2) uses.

The stderr line (one JSON object):

```json
{"severity":"ERROR","component":"app-limits","event":"limit-exceeded","code":"LIMIT_EXCEEDED","exitCode":75,"limit":"max_run_seconds","max":600,"value":750,"runSeconds":750,"tokens":123456}
```

`limit` is the limit that stopped the run, `max` its declared value, `value` the measure in its unit (seconds, or tokens), `runSeconds` and `tokens` both measures at that moment. The 100% line has the same fields, with `severity` `WARNING` and `event` `limit-reached`.

## Model context

The notice is the second text the harness adds to the context on its own (after `app-recovery`'s), `noticeText` in `index.js`; `<limit>` is `time` or `token`:

> Notice: this run has reached its `<limit>` limit. This is an automatic system notice, not a message from the user. Deliver the result you have now, ending the run the way your instructions say. If the run has not ended by 125% of the limit, it is stopped and counted as an error.

Source kind `app-limit-notice`, label `Limit notice`. No values, names or paths. The `app.limit` baseline of `backend_harness/tests/context.sh` guards the time variant (a capture with `max_run_seconds` 60 whose first request outlives it); the unit tests pin both. After changing the text or when it is sent, run `backend_harness/tests/context.sh --build --check`.

## Files

- `index.js`: `parseLimits`, `countTokens`, `noticeText`, `createLimiter` (the counting and the decisions, clock and timer injected), `apply` (the hooks), `LIMIT_EXCEEDED_EXIT`, `MAX_TIMER_MS`, `FLUSH_CAP_MS`.
- `package.json`: private ESM package `dsh-plugin-app-limits`, entry `index.js`.

Tests: `backend_harness/tests/runtime/plugins/dsh-plugin-app-limits/limits.test.mjs` (fake clock and agent), run by `backend_harness/tests/test.sh`.
