/**
 * Enforces an agent's declared run limits from inside its own process: no
 * external ticker, so it works the same on a laptop and in a container.
 *
 * The limits are `max_run_seconds` and `max_tokens` of agents/<name>/agent.yml
 * (null = no limit), which app-agent passes as APP_LIMITS, JSON printed by
 * dsh-plugin-app-tools/cli.js from the one agent.yml parser. `max_attempts` is
 * the queue's (the harness server), not this plugin's.
 *
 * One process is one run (`app-agent run` or `resume`): the clock starts when
 * this plugin is applied at boot, and the token count starts at zero.
 *
 * - 100% of a limit: ONE fixed notice to the model (the limit was reached,
 *   deliver what you have, what happens if not). Only a model response still
 *   streaming with no tool call is interrupted (cancelled), and the notice
 *   starts the next turn. In every other case (a response that has a tool
 *   call, tools in flight, between steps, idle) the notice waits for the next
 *   step boundary (`inject`) without cancelling or waking anything: cutting
 *   there could abort the very delivery the notice asks for (a finalize_* tool,
 *   a write, a query). Counting goes on.
 * - 125% of a limit: one structured line on stderr, a best-effort flush of the
 *   session log (at most FLUSH_CAP_MS), then exit LIMIT_EXCEEDED_EXIT (75),
 *   which the harness server treats as a final failure (no requeue). No
 *   cancel first: dsh's headless runner would see an aborted turn and exit 1
 *   before us.
 *
 * Tokens: what the provider reports per response (the `usage` chunk of each
 * model attempt, retries included), input + output: `inputTokens` +
 * `cacheReadTokens` + `cacheWriteTokens` + `outputTokens` + `reasoningTokens`.
 * dsh's contract makes reasoning a subset of output, but an adapter may report
 * a model's thinking ONLY in `reasoningTokens` (outside outputTokens), so it is
 * added here. An adapter that does include reasoning in output is double
 * counted: the run is cut earlier, never later, which is the safe side.
 * Model calls that do not stream to the agent (compaction's summary) are not
 * counted.
 *
 * The notice is model context. Its text is fixed here and guarded by
 * backend_harness/tests/context.sh (limit baseline + denylist).
 *
 * @module dsh-plugin-app-limits
 */

import z from '@deepseek-ai/schemastery'
import { createUserMessage } from '@deepseek-ai/dsh-llm'

export const name = 'app-limits'

export const Config = z.object({})

/**
 * The exit code of a run stopped at 125% of a limit: LIMIT_EXCEEDED, our own
 * contract with the harness server (a final failure, never requeued). 75 is
 * sysexits' EX_TEMPFAIL, but that meaning is NOT intended: it is only a code
 * neither node, dsh nor app-agent (2) exits with.
 */
export const LIMIT_EXCEEDED_EXIT = 75
export const LIMIT_EXCEEDED_CODE = 'LIMIT_EXCEEDED'

// 125% as a ratio of integers, so the comparison is exact: value*4 >= max*5.
const STOP_NUM = 5
const STOP_DEN = 4

// setTimeout's largest delay; a longer one fires at once (node clamps it to
// 1 ms). A farther threshold just fires early, finds nothing, and re-arms.
export const MAX_TIMER_MS = 2 ** 31 - 1

// The most the 125% stop waits for the session log to flush before exiting.
export const FLUSH_CAP_MS = 1000

// The limit names as agent.yml spells them, and the word the notice uses.
const LIMITS = { max_run_seconds: 'time', max_tokens: 'token' }

/**
 * APP_LIMITS, as app-agent exports it: `{ limits: {max_run_seconds, max_tokens} }`
 * or `{ error }`. Absent or empty is no limits (dsh run by hand, the context
 * capture of the bare profile). Other keys (max_attempts) are ignored.
 */
export function parseLimits(value) {
  if (value === undefined || value === '') return { limits: { max_run_seconds: null, max_tokens: null } }
  let doc
  try {
    doc = JSON.parse(value)
  } catch {
    return { error: 'APP_LIMITS is not JSON' }
  }
  if (doc === null || typeof doc !== 'object' || Array.isArray(doc)) return { error: 'APP_LIMITS is not a JSON object' }
  const limits = {}
  for (const key of Object.keys(LIMITS)) {
    const limit = doc[key]
    if (limit !== null && !(Number.isSafeInteger(limit) && limit >= 1)) return { error: `APP_LIMITS.${key}: a positive integer or null` }
    limits[key] = limit
  }
  return { limits }
}

/** Input + output + reasoning of one provider-reported usage (see the module header). */
export function countTokens(usage) {
  const count = value => (Number.isFinite(value) && value > 0 ? value : 0)
  return count(usage?.inputTokens) + count(usage?.cacheReadTokens) + count(usage?.cacheWriteTokens) + count(usage?.outputTokens) +
    // Thinking an adapter reports outside outputTokens (see the header).
    count(usage?.reasoningTokens)
}

// Shown to the model once, at 100%. Short and factual: which limit, that it is
// not from the user, what to do, and what happens otherwise. "The way your
// instructions say" because each agent ends differently (a final answer, a
// tool such as finalize_summary). No values, names or paths.
export function noticeText(limit) {
  return `Notice: this run has reached its ${LIMITS[limit]} limit. ` +
    'This is an automatic system notice, not a message from the user. ' +
    'Deliver the result you have now, ending the run the way your instructions say. ' +
    'If the run has not ended by 125% of the limit, it is stopped and counted as an error.'
}

/**
 * The counting and the decisions, with the clock and the timer injected.
 * `now()` is in milliseconds; `schedule(ms, fn)` returns a cancel function.
 * Calls `notice(facts)` at most once, then `stop(facts)` at most once; facts
 * are `{ limit, max, value, runSeconds, tokens }` (value in the limit's unit,
 * seconds or tokens).
 */
export function createLimiter(limits, { now, schedule, notice, stop }) {
  const started = now()
  let tokens = 0
  let noticed = false
  let stopped = false
  let cancelTimer

  const elapsedMs = () => now() - started
  const facts = (limit, max, value) => ({
    limit, max, value,
    runSeconds: Math.round(elapsedMs()) / 1000,
    tokens,
  })

  // Time in milliseconds against max_run_seconds * 1000, tokens as counted.
  const measures = () => [
    ['max_run_seconds', limits.max_run_seconds, elapsedMs(), 1000],
    ['max_tokens', limits.max_tokens, tokens, 1],
  ].filter(([, max]) => max !== null)

  function evaluate() {
    if (stopped) return
    for (const [limit, max, value, scale] of measures()) {
      if (value * STOP_DEN >= max * scale * STOP_NUM) {
        stopped = true
        cancelTimer?.()
        stop(facts(limit, max, scale === 1 ? value : Math.round(value) / 1000))
        return
      }
    }
    if (noticed) return
    for (const [limit, max, value, scale] of measures()) {
      if (value >= max * scale) {
        noticed = true
        notice(facts(limit, max, scale === 1 ? value : Math.round(value) / 1000))
        break
      }
    }
  }

  // One timer, for the next time threshold still ahead: 100% until the notice
  // (by either limit), then 125%. Re-armed from the clock, so a timer that
  // fires early only waits again.
  function arm() {
    if (limits.max_run_seconds === null || stopped) return
    const target = limits.max_run_seconds * (noticed ? 1000 * STOP_NUM / STOP_DEN : 1000)
    cancelTimer = schedule(Math.min(MAX_TIMER_MS, Math.max(1, Math.ceil(target - elapsedMs()))), () => {
      evaluate()
      arm()
    })
  }
  arm()

  return {
    /** Add one response's usage and decide. */
    addUsage(usage) {
      tokens += countTokens(usage)
      evaluate()
    },
    dispose() {
      cancelTimer?.()
    },
    get tokens() { return tokens },
    get noticed() { return noticed },
    get stopped() { return stopped },
  }
}

const log = (stderr, severity, event, fields) => {
  stderr.write(`${JSON.stringify({ severity, component: name, event, ...fields })}\n`)
}

/**
 * `deps` is for the tests; dsh calls `apply(ctx, config)`. `schedule(ms, fn,
 * { ref })` returns a cancel function; `timers` are the real ones it uses.
 */
export function apply(ctx, _config, deps = {}) {
  const {
    env = process.env,
    now = () => performance.now(),
    timers = globalThis,
    schedule = (ms, fn, { ref = false } = {}) => {
      const timer = timers.setTimeout(fn, ms)
      // A pending limit must never keep a finished run alive (unref). The
      // flush cap is ref'd: exiting with 75 must not turn into a quiet exit 0.
      if (!ref) timer.unref?.()
      return () => timers.clearTimeout(timer)
    },
    exit = code => process.exit(code),
    stderr = process.stderr,
  } = deps

  const { limits, error } = parseLimits(env.APP_LIMITS)
  if (error) {
    // app-agent prints APP_LIMITS from the checked agent.yml, so this is a broken
    // launcher; booting without the limits would fail open.
    log(stderr, 'ERROR', 'bad-limits', { message: error })
    exit(2)
    return
  }
  if (limits.max_run_seconds === null && limits.max_tokens === null) return

  // Per agent, its latest model attempt: `streaming` from its start frame
  // (dsh publishes it as the request opens, before any chunk) to its end
  // frame; `tools` once it has a tool call, until the next attempt starts (the
  // calls run between the two). `usage`: its one usage chunk.
  const agents = new Map()
  const stateOf = agent => {
    if (!agents.has(agent)) agents.set(agent, { attemptId: undefined, streaming: false, tools: false, usage: undefined })
    return agents.get(agent)
  }

  // Cancel only a response still streaming with no tool call: nothing of it is
  // done yet, and the notice opens the next turn. Otherwise inject: the notice
  // joins the next step boundary, after the tools in flight finish.
  const deliver = (agent, limit) => {
    const message = createUserMessage({
      source: { kind: 'app-limit-notice', label: 'Limit notice', form: 'notice', summary: `${limit} reached` },
      content: [{ type: 'text', text: noticeText(limit) }],
    })
    const state = stateOf(agent)
    if (agent.status === 'running' && state.streaming && !state.tools) {
      agent.cancel({ kind: 'hook', reason: `${name}: ${limit} reached` })
      agent.followup(message)
    } else {
      agent.inject(message)
    }
  }

  // Best effort: the session log batches writes (200 ms in the jsonl backend),
  // and process.exit drops what is still batched. Exit 75 regardless, after
  // the flush, its failure, or FLUSH_CAP_MS.
  const exitAfterFlush = () => {
    const persistence = ctx.get?.('sessionPersistence')
    if (typeof persistence?.flush !== 'function') {
      exit(LIMIT_EXCEEDED_EXIT)
      return
    }
    let done = false
    let cancelCap
    const finish = () => {
      if (done) return
      done = true
      cancelCap?.()
      exit(LIMIT_EXCEEDED_EXIT)
    }
    cancelCap = schedule(FLUSH_CAP_MS, finish, { ref: true })
    Promise.resolve().then(() => persistence.flush()).then(finish, finish)
  }

  const limiter = createLimiter(limits, {
    now,
    schedule,
    notice: facts => {
      log(stderr, 'WARNING', 'limit-reached', facts)
      for (const agent of agents.keys()) deliver(agent, facts.limit)
    },
    stop: facts => {
      log(stderr, 'ERROR', 'limit-exceeded', { code: LIMIT_EXCEEDED_CODE, exitCode: LIMIT_EXCEEDED_EXIT, ...facts })
      exitAfterFlush()
    },
  })

  const disposers = [
    ctx.on('agent/created', ({ agent }) => { stateOf(agent) }),
    ctx.on('agent/disposed', ({ agent }) => { agents.delete(agent) }),
    ctx.on('agent/assistant-stream', ({ agent, frame }) => {
      if (agent === undefined) return
      const state = stateOf(agent)
      if (frame.type === 'start') {
        Object.assign(state, { attemptId: frame.attemptId, streaming: true, tools: false, usage: undefined })
        return
      }
      if (frame.attemptId !== state.attemptId) return
      if (frame.type === 'chunk') {
        if (frame.chunk.type === 'usage') state.usage = frame.chunk.usage
        else if (frame.chunk.type === 'tool-call-delta' || frame.chunk.block?.type === 'tool-call') state.tools = true
        return
      }
      // 'end': the attempt is settled (its message committed, or abandoned),
      // so the decision never cuts a response in half; `tools` stays set while
      // its calls run.
      state.streaming = false
      const usage = state.usage
      state.usage = undefined
      if (usage !== undefined) limiter.addUsage(usage)
    }),
  ]
  ctx.effect(() => () => {
    limiter.dispose()
    for (const dispose of disposers) dispose()
  }, 'app-limits: stop counting')
}
