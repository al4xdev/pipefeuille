# dsh-plugin-app-recovery

Recovers from unexpected model-request failures by retrying once with a fixed notice to the model, and writes a **mock** log line to stderr for every request error. Loaded by every agent through the `app` profile (`cordis.patch.yml`, entry `id: app-recovery`, `name: dsh-plugin-app-recovery`, `maxRecoveriesPerTurn: 1`). Plugin name: `app-recovery`.

Config (`Config` in `index.js`):

| Key | Default | Meaning |
|---|---|---|
| `maxRecoveriesPerTurn` | `1` | Recoveries allowed per agent per turn; `0` disables recovery. |
| `permanentCodes` | `AUTH`, `QUOTA`, `CONTEXT_WINDOW_EXCEEDED`, `MISSING_CONFIG`, `MISSING_CREDENTIAL`, `UNSUPPORTED_CONTENT`, `ABORTED`, `INVALID_HISTORY`, `INVALID_CREDENTIAL`, `ACCOUNT_SIGN_IN_REQUIRED`, `ACCOUNT_TOKEN_INVALID`, `UNSUPPORTED_REASONING_EFFORT` | Codes that fail the turn without recovery. `INVALID_HISTORY` is here because a retry resends the same unserializable history. |

## Tools

None. The plugin works through one hook.

### `agent/request-error`

Classifies `failure.code` (missing code = `UNKNOWN`) by the code alone, so its order against dsh's built-in `llm-retry` does not matter:

- **transient**: a code in the route's resolved `retryPolicy.retryableCodes`, which the hook payload carries. The one list is the provider entry's `retryPolicy` (the built-in `llm-deepseek` entry in `cordis.patch.yml`, written out with dsh's default: `mode: normal`, five retries of `EMPTY_RESPONSE`, `RATE_LIMIT`, `SERVER`, `TIMEOUT`, `TRANSPORT`; under `mode: always` llm-retry asks downstream recovery first, so other codes still get the notice). Logged with severity `WARNING`, decision `llm-retry`, then passed on (`next()`); the retry itself is `llm-retry`'s.
- **permanent**: any code in `permanentCodes`. Logged `ERROR`, decision `fail`, passed on.
- **unexpected**: everything else (e.g. `PROVIDER_TERMINATED`, `MALFORMED_RESPONSE`, `STREAM_CLOSED`, `INVALID_REQUEST`, `HTTP_<status>`, `UNKNOWN`). If the turn's budget is not used up and the request was not aborted, it appends a user message (source kind `app-recovery-notice`, label `Recovery notice`) to the session and returns `{ kind: 'retry' }`; it logs `WARNING`, decision `recover`. Otherwise it logs `ERROR`, decision `fail`, reason `recovery-budget-exhausted` or `aborted`, and passes on.

The per-turn count lives in memory, keyed by agent id: a restarted process forgets it, so a resumed turn may get one more recovery. The listener is removed when the plugin's effect is disposed.

### Mock log (stderr)

One JSON line per request error: `severity`, `component: "app-recovery"`, `event: "request-error"`, `mock: true`, `agentId`, `sessionId`, `turn`, `step`, `provider`, `code`, `kind`, `message` (first 200 chars of the provider message), `decision`, plus `reason`/`recoveries` or `attempt`/`maxRecoveries`. A placeholder: fields, correlation, sinks and PII policy are still to be designed. The harness server relays these structured lines to its own log with the `process_id`.

## Model context

The recovery notice is the only text the harness adds to the context on its own (`noticeText` in `index.js`):

> Notice: your previous response could not be completed (error `<code>`). This is an automatic system notice, not a message from the user. Retry `<attempt>` of `<max>`: answer the last user message again; if you were calling a function, make sure the call is well formed.

Only the error code enters the context, never the provider's message. The `app.recovery` baseline of `backend_harness/tests/context.sh` guards this text; after changing it (or the classification that triggers it) run `backend_harness/tests/context.sh --build --check`.

## Files

- `index.js`: config schema, classification, notice text, the `agent/request-error` hook and the mock log.
- `package.json`: private ESM package `dsh-plugin-app-recovery`, entry `index.js`.