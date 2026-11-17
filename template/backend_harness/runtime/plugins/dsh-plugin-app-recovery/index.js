/**
 * Recovery from unexpected model-request failures, plus a mock log of every
 * failure the agent sees.
 *
 * Three kinds of failure reach `agent/request-error`:
 * - transient: the codes the route's `retryPolicy` retries (the provider
 *   entry's config: llm-deepseek's in the profile). Owned by dsh's built-in
 *   llm-retry; only logged here. The policy arrives in the payload, so there
 *   is no second list.
 * - permanent (auth, quota, context window, config, a corrupt history): the
 *   same request fails the same way. Logged and passed through, so the turn fails.
 * - unexpected, everything else (PROVIDER_TERMINATED, MALFORMED_RESPONSE,
 *   STREAM_CLOSED, INVALID_REQUEST, unknown codes): retried up to
 *   `maxRecoveriesPerTurn` times, each after a notice telling the model the
 *   last attempt failed.
 *
 * Deciding on the code alone keeps this independent of its order against
 * llm-retry in the middleware chain: neither ever claims the other's codes.
 *
 * The notice is model context. Its text is fixed here and guarded by
 * backend_harness/tests/context.sh (recovery baseline + denylist).
 *
 * @module dsh-plugin-app-recovery
 */

import z from '@deepseek-ai/schemastery'
import { createUserMessage } from '@deepseek-ai/dsh-llm'

export const name = 'app-recovery'

export const Config = z.object({
  maxRecoveriesPerTurn: z.number().step(1).min(0).default(1),
  // INVALID_HISTORY: the adapter cannot serialize the stored history, and a
  // retry resends exactly that history.
  permanentCodes: z.array(z.string()).default([
    'AUTH', 'QUOTA', 'CONTEXT_WINDOW_EXCEEDED', 'MISSING_CONFIG', 'MISSING_CREDENTIAL',
    'UNSUPPORTED_CONTENT', 'ABORTED', 'INVALID_HISTORY',
    // The built-in provider's credential and sign-in failures, and an effort
    // the model does not take: the same request fails the same way.
    'INVALID_CREDENTIAL', 'ACCOUNT_SIGN_IN_REQUIRED', 'ACCOUNT_TOKEN_INVALID', 'UNSUPPORTED_REASONING_EFFORT',
  ]),
})

// MOCK LOG: a placeholder for the real logging design (structured fields,
// correlation with the REST request, sinks, retention, PII policy). One JSON line
// on stderr, which the harness server relays to its own log (it relays
// structured lines only). The error message is cut short because it can echo
// request content; the real design decides what may be logged at all.
function mockLog(severity, event, fields) {
  process.stderr.write(`${JSON.stringify({ severity, component: name, event, mock: true, ...fields })}\n`)
}

// Shown to the model before the retry. Kept short and factual: what failed, that
// it is not from the user, and what to do. The provider's message is NOT included,
// so no provider text the model could follow as instructions enters the context.
export function noticeText(code, attempt, max) {
  return `Notice: your previous response could not be completed (error ${code}). ` +
    `This is an automatic system notice, not a message from the user. ` +
    `Retry ${attempt} of ${max}: answer the last user message again; if you were ` +
    'calling a function, make sure the call is well formed.'
}

/**
 * `retryPolicy` is the route's resolved policy from the payload (absent: no
 * llm-retry). Only its `retryableCodes` count, in any mode: under `always`
 * llm-retry lets downstream recovery act first, so claiming every code here
 * would silence the notice.
 */
export function classify(code, config, retryPolicy) {
  if (retryPolicy?.retryableCodes?.includes(code)) return 'transient'
  if (config.permanentCodes.includes(code)) return 'permanent'
  return 'unexpected'
}

export function apply(ctx, config) {
  // In memory, per agent and turn: a mock like the log. A restarted process
  // forgets it, which at worst allows one more recovery in a resumed turn.
  const used = new Map()

  const dispose = ctx.on('agent/request-error', (payload, next) => {
    const { agent, turn, step, provider, failure, retryPolicy } = payload
    const code = failure?.code ?? 'UNKNOWN'
    const kind = classify(code, config, retryPolicy)
    const base = {
      agentId: agent?.id, sessionId: agent?.session?.id, turn, step, provider, code, kind,
      message: String(failure?.message ?? '').slice(0, 200),
    }
    if (kind !== 'unexpected') {
      mockLog(kind === 'transient' ? 'WARNING' : 'ERROR', 'request-error', { ...base, decision: kind === 'transient' ? 'llm-retry' : 'fail' })
      return next()
    }

    const previous = used.get(agent.id)
    const count = previous?.turn === turn ? previous.count : 0
    if (count >= config.maxRecoveriesPerTurn || payload.signal?.aborted) {
      mockLog('ERROR', 'request-error', { ...base, decision: 'fail', reason: payload.signal?.aborted ? 'aborted' : 'recovery-budget-exhausted', recoveries: count })
      return next()
    }
    const attempt = count + 1
    used.set(agent.id, { turn, count: attempt })
    agent.session.append('user/message', createUserMessage({
      source: { kind: 'app-recovery-notice', label: 'Recovery notice', form: 'notice', summary: `retry after ${code}` },
      content: [{ type: 'text', text: noticeText(code, attempt, config.maxRecoveriesPerTurn) }],
    }), { surfaceOp: 'append' })
    mockLog('WARNING', 'request-error', { ...base, decision: 'recover', attempt, maxRecoveries: config.maxRecoveriesPerTurn })
    return Promise.resolve({ kind: 'retry' })
  })
  ctx.effect(() => dispose, 'app-recovery: stop observing request errors')
}