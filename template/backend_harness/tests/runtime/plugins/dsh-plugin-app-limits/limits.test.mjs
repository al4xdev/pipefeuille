// dsh-plugin-app-limits: APP_LIMITS, the token count, the notice, and the
// decisions at 100% and 125%, on a fake clock and a fake agent (no real
// waits). Runs in the harness image, against the installed plugin:
//
//   backend_harness/tests/test.sh
import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'

const PLUGIN = '/opt/dsh/node_modules/dsh-plugin-app-limits/index.js'
const {
  FLUSH_CAP_MS, LIMIT_EXCEEDED_EXIT, MAX_TIMER_MS, apply, countTokens, createLimiter, noticeText, parseLimits,
} = await import(PLUGIN)

// Let pending promise callbacks run (the flush before exit 75 is async).
const settle = () => new Promise(resolve => setImmediate(resolve))

// A clock that moves only when told, and timers that fire when it passes them.
function fakeClock() {
  let time = 0
  const timers = []
  return {
    now: () => time,
    schedule: (ms, fn) => {
      const timer = { at: time + ms, fn, cancelled: false }
      timers.push(timer)
      return () => { timer.cancelled = true }
    },
    advance(ms) {
      const until = time + ms
      for (;;) {
        const due = timers.filter(timer => !timer.cancelled && timer.at <= until).sort((a, b) => a.at - b.at)[0]
        if (!due) break
        due.cancelled = true
        time = due.at
        due.fn()
      }
      time = until
    },
    get pending() { return timers.filter(timer => !timer.cancelled).length },
  }
}

function fakeCtx(services = {}) {
  const handlers = new Map()
  let cleanup
  return {
    get: service => services[service],
    on(event, fn) {
      handlers.set(event, fn)
      return () => handlers.delete(event)
    },
    effect(fn) { cleanup = fn() },
    emit(event, payload) { return handlers.get(event)?.(payload) },
    dispose() { cleanup?.() },
    get events() { return [...handlers.keys()].sort() },
  }
}

function fakeAgent(status = 'running') {
  const calls = []
  return {
    status,
    calls,
    cancel: cause => calls.push(['cancel', cause]),
    followup: message => calls.push(['followup', message]),
    inject: message => calls.push(['inject', message]),
  }
}

// apply() on fakes: the plugin, its agent, and what it wrote and exited with.
function boot(limits, status, { services } = {}) {
  const clock = fakeClock()
  const ctx = fakeCtx(services)
  const exits = []
  const lines = []
  const env = limits === undefined ? {} : { APP_LIMITS: typeof limits === 'string' ? limits : JSON.stringify(limits) }
  apply(ctx, {}, {
    env, now: clock.now, schedule: clock.schedule,
    exit: code => exits.push(code),
    stderr: { write: line => lines.push(line) },
  })
  const agent = fakeAgent(status)
  ctx.emit('agent/created', { agent })
  let attempt = 0
  // One model attempt, framed as the agent loop publishes it: its start frame
  // at once (dsh sends it as the request opens), then chunks, then end().
  const stream = () => {
    const attemptId = `attempt-${++attempt}`
    const frame = frame => ctx.emit('agent/assistant-stream', { agent, frame: { attemptId, ...frame } })
    frame({ type: 'start', turn: 1, step: attempt })
    return {
      toolCall: () => frame({ type: 'chunk', chunk: { type: 'tool-call-delta', index: 0, id: 'call', name: 'finalize_summary', argumentsDelta: '{}' } }),
      end: usage => {
        if (usage) frame({ type: 'chunk', chunk: { type: 'usage', usage } })
        frame({ type: 'chunk', chunk: { type: 'finish', reason: { kind: 'stop' } } })
        frame({ type: 'end', index: 3, outcome: { kind: 'committed', eventType: 'assistant/message', seq: attempt } })
      },
    }
  }
  // A whole response.
  const respond = (usage, { tools = false } = {}) => {
    const open = stream()
    if (tools) open.toolCall()
    open.end(usage)
  }
  return { clock, ctx, agent, exits, lines, stream, respond, logged: () => lines.map(line => JSON.parse(line)) }
}

const kinds = agent => agent.calls.map(([kind]) => kind)
const noticeOf = agent => agent.calls.find(([kind]) => kind !== 'cancel')?.[1]

test('APP_LIMITS: absent is no limits, a bad value is refused, max_attempts is not ours', () => {
  assert.deepEqual(parseLimits(undefined), { limits: { max_run_seconds: null, max_tokens: null } })
  assert.deepEqual(parseLimits(''), { limits: { max_run_seconds: null, max_tokens: null } })
  assert.deepEqual(parseLimits('{"max_run_seconds":600,"max_tokens":null,"max_attempts":3}'), { limits: { max_run_seconds: 600, max_tokens: null } })
  for (const [value, pattern] of [
    ['{', /not JSON/],
    ['[]', /not a JSON object/],
    ['null', /not a JSON object/],
    ['{"max_tokens":null}', /max_run_seconds: a positive integer or null/],
    ['{"max_run_seconds":0,"max_tokens":null}', /max_run_seconds/],
    ['{"max_run_seconds":1.5,"max_tokens":null}', /max_run_seconds/],
    ['{"max_run_seconds":null,"max_tokens":"100"}', /max_tokens/],
  ]) {
    assert.match(parseLimits(value).error, pattern, value)
  }
})

test('tokens: input (uncached, cache read and write) plus output plus reasoning, as reported', () => {
  assert.equal(countTokens({ inputTokens: 10, outputTokens: 5 }), 15)
  // reasoningTokens is added: an adapter may report thinking only there.
  assert.equal(countTokens({ inputTokens: 10, outputTokens: 5, cacheReadTokens: 100, cacheWriteTokens: 1, reasoningTokens: 7 }), 123)
  assert.equal(countTokens({ inputTokens: -1, outputTokens: Number.NaN, reasoningTokens: -3 }), 0)
  assert.equal(countTokens(undefined), 0)
})

test('tokens: thinking reported in reasoningTokens, outside outputTokens, counts toward max_tokens', () => {
  const run = boot({ max_run_seconds: null, max_tokens: 100 })
  // One response whose adapter reports output 10 and thinking 30 apart.
  run.respond({ inputTokens: 60, outputTokens: 10, reasoningTokens: 29 }, { tools: true })
  assert.deepEqual(run.agent.calls, [], '99 tokens: under the limit')
  run.respond({ inputTokens: 0, outputTokens: 0, reasoningTokens: 1 }, { tools: true })
  assert.deepEqual(kinds(run.agent), ['inject'])
  assert.deepEqual(run.logged().map(line => [line.event, line.value]), [['limit-reached', 100]])
  run.respond({ reasoningTokens: 25 }, { tools: true })
  assert.deepEqual(run.exits, [75])
  assert.equal(run.logged()[1].tokens, 125)
})

test('the notice is fixed, short, and names only the limit', () => {
  const tail = 'This is an automatic system notice, not a message from the user. ' +
    'Deliver the result you have now, ending the run the way your instructions say. ' +
    'If the run has not ended by 125% of the limit, it is stopped and counted as an error.'
  assert.equal(noticeText('max_run_seconds'), `Notice: this run has reached its time limit. ${tail}`)
  assert.equal(noticeText('max_tokens'), `Notice: this run has reached its token limit. ${tail}`)
  // The context check's denylist, applied here too (the capture shows only the time variant).
  const denied = readFileSync('denylist.txt', 'utf8').split('\n').filter(line => line && !line.startsWith('#'))
  for (const limit of ['max_run_seconds', 'max_tokens']) {
    const text = noticeText(limit).toLowerCase()
    assert.deepEqual(denied.filter(phrase => text.includes(phrase.toLowerCase())), [], limit)
    assert.ok(!text.includes('/'), 'no paths')
  }
  assert.equal(LIMIT_EXCEEDED_EXIT, 75)
})

test('no limits (null): nothing is watched, nothing happens', () => {
  for (const limits of [undefined, { max_run_seconds: null, max_tokens: null, max_attempts: 3 }]) {
    const run = boot(limits)
    assert.deepEqual(run.ctx.events, [])
    assert.equal(run.clock.pending, 0)
    run.respond({ inputTokens: 10 ** 9, outputTokens: 10 ** 9 })
    run.clock.advance(10 ** 9)
    assert.deepEqual([run.agent.calls, run.exits, run.lines], [[], [], []])
  }
  const notice = []
  const limiter = createLimiter({ max_run_seconds: null, max_tokens: null }, { ...fakeClock(), notice: f => notice.push(f), stop: f => notice.push(f) })
  limiter.addUsage({ inputTokens: 10 ** 12, outputTokens: 0 })
  assert.deepEqual(notice, [])
})

test('time: the notice at exactly 100% interrupts a streaming response, once; exit 75 at exactly 125%', () => {
  const run = boot({ max_run_seconds: 10, max_tokens: null })
  // A model response still streaming, with no tool call yet.
  run.stream()
  run.clock.advance(9_999)
  assert.deepEqual(run.agent.calls, [])
  run.clock.advance(1)
  assert.deepEqual(kinds(run.agent), ['cancel', 'followup'])
  assert.deepEqual(run.agent.calls[0][1], { kind: 'hook', reason: 'app-limits: max_run_seconds reached' })
  const message = noticeOf(run.agent)
  assert.equal(message.source.kind, 'app-limit-notice')
  assert.deepEqual(message.content, [{ type: 'text', text: noticeText('max_run_seconds') }])
  assert.deepEqual(run.logged(), [{ severity: 'WARNING', component: 'app-limits', event: 'limit-reached', limit: 'max_run_seconds', max: 10, value: 10, runSeconds: 10, tokens: 0 }])
  // Counting goes on, with no second notice.
  run.respond({ inputTokens: 5, outputTokens: 5 })
  run.clock.advance(2_499)
  assert.deepEqual([kinds(run.agent), run.exits], [['cancel', 'followup'], []])
  run.clock.advance(1)
  assert.deepEqual(run.exits, [75])
  assert.equal(run.lines.length, 2)
  assert.deepEqual(run.logged()[1], {
    severity: 'ERROR', component: 'app-limits', event: 'limit-exceeded', code: 'LIMIT_EXCEEDED', exitCode: 75,
    limit: 'max_run_seconds', max: 10, value: 12.5, runSeconds: 12.5, tokens: 10,
  })
  // Stopped is final: no timer left, nothing more happens.
  assert.equal(run.clock.pending, 0)
  run.clock.advance(60_000)
  run.respond({ inputTokens: 5 })
  assert.deepEqual(run.exits, [75])
})

test('time: a timer that fires early only waits again', () => {
  const clock = fakeClock()
  const seen = []
  let early = true
  const limiter = createLimiter({ max_run_seconds: 1, max_tokens: null }, {
    now: clock.now,
    // The first timer fires 10 ms before it is due.
    schedule: (ms, fn) => clock.schedule(early ? (early = false, ms - 10) : ms, fn),
    notice: facts => seen.push(['notice', facts.value]),
    stop: facts => seen.push(['stop', facts.value]),
  })
  clock.advance(990)
  assert.deepEqual(seen, [])
  clock.advance(10)
  assert.deepEqual(seen, [['notice', 1]])
  clock.advance(250)
  assert.deepEqual(seen, [['notice', 1], ['stop', 1.25]])
  assert.ok(limiter.stopped)
})

test('tokens: 100% is reached at the limit, after the response settles; exit 75 at 125%', () => {
  const run = boot({ max_run_seconds: null, max_tokens: 100 })
  assert.equal(run.clock.pending, 0, 'no timer without max_run_seconds')
  run.respond({ inputTokens: 60, outputTokens: 39 }, { tools: true })
  assert.deepEqual(run.agent.calls, [])
  run.respond({ inputTokens: 0, outputTokens: 1 }, { tools: true })
  // A response with tool calls: its tools must run, so nothing is cancelled.
  assert.deepEqual(kinds(run.agent), ['inject'])
  assert.equal(noticeOf(run.agent).content[0].text, noticeText('max_tokens'))
  run.respond({ inputTokens: 24 }, { tools: true })
  assert.deepEqual(run.exits, [])
  run.respond({ cacheReadTokens: 1 })
  assert.deepEqual(run.exits, [75])
  assert.deepEqual(run.logged().map(line => [line.event, line.limit, line.value, line.max]), [
    ['limit-reached', 'max_tokens', 100, 100],
    ['limit-exceeded', 'max_tokens', 125, 100],
  ])
  assert.equal(kinds(run.agent).length, 1, 'one notice only')
})

test('tokens: a final answer (no tool calls) is not cut; the notice waits for a next step', () => {
  const run = boot({ max_run_seconds: null, max_tokens: 100 })
  run.respond({ inputTokens: 100, outputTokens: 0 })
  assert.deepEqual(kinds(run.agent), ['inject'])
  assert.equal(noticeOf(run.agent).content[0].text, noticeText('max_tokens'))
})

test('an idle agent is not woken: the notice waits for its next step', () => {
  const run = boot({ max_run_seconds: 1, max_tokens: null }, 'idle')
  run.clock.advance(1_000)
  assert.deepEqual(kinds(run.agent), ['inject'])
})

test('one notice for both limits; each still stops the run at its own 125%', () => {
  const run = boot({ max_run_seconds: 10, max_tokens: 100 })
  run.respond({ inputTokens: 100 }, { tools: true })
  assert.deepEqual(kinds(run.agent), ['inject'])
  run.stream()
  run.clock.advance(10_000)
  assert.deepEqual(kinds(run.agent), ['inject'], 'no second notice at the time limit')
  run.clock.advance(2_500)
  assert.deepEqual(run.exits, [75])
  assert.equal(run.logged()[1].limit, 'max_run_seconds')
})

test('a response that jumps past 125% stops the run without a notice', () => {
  const run = boot({ max_run_seconds: null, max_tokens: 100 })
  run.respond({ inputTokens: 125 }, { tools: true })
  assert.deepEqual([run.agent.calls, run.exits], [[], [75]])
  assert.deepEqual(run.logged().map(line => line.event), ['limit-exceeded'])
})

test('a response without usage counts nothing; frames of unknown attempts are ignored', () => {
  const run = boot({ max_run_seconds: null, max_tokens: 1 })
  run.respond(undefined, { tools: true })
  run.ctx.emit('agent/assistant-stream', { agent: run.agent, frame: { type: 'end', attemptId: 'other', index: 0, outcome: { kind: 'abandoned' } } })
  assert.deepEqual([run.agent.calls, run.exits], [[], []])
})

test('a bad APP_LIMITS stops the boot (exit 2), it never runs without its limits', () => {
  const run = boot('{"max_run_seconds":-1,"max_tokens":null}')
  assert.deepEqual(run.exits, [2])
  assert.equal(run.logged()[0].event, 'bad-limits')
  assert.deepEqual(run.ctx.events, [])
})

test('disposal cancels the timer and the listeners', () => {
  const run = boot({ max_run_seconds: 10, max_tokens: 100 })
  assert.deepEqual(run.ctx.events, ['agent/assistant-stream', 'agent/created', 'agent/disposed'])
  run.ctx.dispose()
  assert.deepEqual(run.ctx.events, [])
  assert.equal(run.clock.pending, 0)
  run.clock.advance(60_000)
  assert.deepEqual([run.agent.calls, run.exits], [[], []])
})

test('a disposed agent gets no notice', () => {
  const run = boot({ max_run_seconds: 1, max_tokens: null })
  run.ctx.emit('agent/disposed', { agent: run.agent })
  run.clock.advance(1_000)
  assert.deepEqual(run.agent.calls, [])
})

// (C) Where the notice lands: only a response still streaming with no tool call is cut.

test('100% while a response streams with no tool call: cancel, and the notice opens the next turn', () => {
  const run = boot({ max_run_seconds: 1, max_tokens: null })
  run.stream()
  run.clock.advance(1_000)
  assert.deepEqual(kinds(run.agent), ['cancel', 'followup'])
})

test('100% while a response streams and already has a tool call: inject, nothing cancelled', () => {
  const run = boot({ max_run_seconds: 1, max_tokens: null })
  run.stream().toolCall()
  run.clock.advance(1_000)
  assert.deepEqual(kinds(run.agent), ['inject'])
})

test('100% while the tools of a response run (a finalize_* tool, a query, a write): inject', () => {
  const run = boot({ max_run_seconds: 1, max_tokens: null })
  run.respond({ inputTokens: 1 }, { tools: true })
  run.clock.advance(1_000)
  assert.deepEqual(kinds(run.agent), ['inject'])
})

test('100% between steps (a response ended with no tool call, turn still running): inject', () => {
  const run = boot({ max_run_seconds: 1, max_tokens: null })
  run.respond({ inputTokens: 1 })
  run.clock.advance(1_000)
  assert.deepEqual(kinds(run.agent), ['inject'])
})

test('a new attempt clears the previous one\'s tool call: streaming again with none is cut', () => {
  const run = boot({ max_run_seconds: 1, max_tokens: null })
  run.respond({ inputTokens: 1 }, { tools: true })
  run.stream()
  run.clock.advance(1_000)
  assert.deepEqual(kinds(run.agent), ['cancel', 'followup'])
})

// (A) Timer delays past setTimeout's range.

test('a limit past setTimeout\'s range: every delay is clamped to 2^31-1 ms and fires nothing early', () => {
  assert.equal(MAX_TIMER_MS, 2 ** 31 - 1)
  const clock = fakeClock()
  const delays = []
  const seen = []
  const max = 10 ** 7 // seconds: 10^10 ms, beyond 2^31-1
  createLimiter({ max_run_seconds: max, max_tokens: null }, {
    now: clock.now,
    schedule: (ms, fn) => { delays.push(ms); return clock.schedule(ms, fn) },
    notice: () => seen.push('notice'),
    stop: () => seen.push('stop'),
  })
  clock.advance(max * 1000 - 1)
  assert.deepEqual(seen, [], 'the clamped timer fired early, found nothing, and re-armed')
  assert.ok(delays.length > 1)
  assert.ok(delays.every(ms => ms >= 1 && ms <= MAX_TIMER_MS), `delays ${delays}`)
  clock.advance(1)
  assert.deepEqual(seen, ['notice'])
  assert.ok(delays.every(ms => ms <= MAX_TIMER_MS))
})

// (B) The real timer: unref'd, and cleared when the plugin's scope ends.

test('real timer: unref\'d after apply() (never keeps a run alive), cleared on disposal', () => {
  const created = []
  const cleared = []
  const timers = {
    setTimeout: (fn, ms) => { const timer = setTimeout(fn, ms); created.push(timer); return timer },
    clearTimeout: timer => { cleared.push(timer); clearTimeout(timer) },
  }
  const ctx = fakeCtx()
  apply(ctx, {}, { env: { APP_LIMITS: JSON.stringify({ max_run_seconds: 3600, max_tokens: null }) }, timers, stderr: { write() {} }, exit() {} })
  try {
    assert.equal(created.length, 1)
    assert.equal(created[0].hasRef(), false, 'the limit timer must be unref\'d')
  } finally {
    ctx.dispose()
  }
  assert.deepEqual(cleared, created, 'the agent\'s end (scope disposal) clears it')
})

test('real timer: a process with a long limit pending still exits at once when its work ends', () => {
  const script = `
    const { apply } = await import(${JSON.stringify(PLUGIN)})
    apply({ on: () => () => {}, effect() {} }, {}, { env: { APP_LIMITS: '{"max_run_seconds":3600,"max_tokens":null}' } })
  `
  const started = Date.now()
  const result = spawnSync(process.execPath, ['--input-type=module', '-e', script], { timeout: 15_000, encoding: 'utf8' })
  assert.equal(result.error, undefined, 'still alive after 15 s: the timer kept it')
  assert.deepEqual([result.status, result.stderr], [0, ''])
  assert.ok(Date.now() - started < 15_000)
})

// (D) The 125% stop flushes the session log first, best effort, capped.

const stopWith = flush => {
  const flushes = []
  const run = boot({ max_run_seconds: null, max_tokens: 100 }, 'running', {
    services: { sessionPersistence: { flush: () => { flushes.push(true); return flush() } } },
  })
  run.respond({ inputTokens: 125 }, { tools: true })
  return { run, flushes }
}

test('125%: exit 75 once the session log is flushed, not before', async () => {
  let resolve
  const { run, flushes } = stopWith(() => new Promise(done => { resolve = done }))
  await settle()
  assert.deepEqual([flushes.length, run.exits], [1, []])
  assert.equal(run.logged()[0].event, 'limit-exceeded', 'the line is written before the flush')
  resolve()
  await settle()
  assert.deepEqual(run.exits, [75])
  assert.equal(run.clock.pending, 0, 'the cap is cancelled')
})

test('125%: a flush that fails (rejects or throws) still exits 75', async () => {
  for (const flush of [() => Promise.reject(new Error('disk')), () => { throw new Error('disk') }]) {
    const { run } = stopWith(flush)
    await settle()
    assert.deepEqual(run.exits, [75])
  }
})

test('125%: a flush that hangs is cut at FLUSH_CAP_MS (1 s): exit 75 once', async () => {
  assert.equal(FLUSH_CAP_MS, 1000)
  let resolve
  const { run } = stopWith(() => new Promise(done => { resolve = done }))
  await settle()
  run.clock.advance(FLUSH_CAP_MS - 1)
  assert.deepEqual(run.exits, [])
  run.clock.advance(1)
  assert.deepEqual(run.exits, [75])
  resolve()
  await settle()
  assert.deepEqual(run.exits, [75], 'a late flush does not exit again')
})

test('125% with no session persistence: exit 75 at once', () => {
  const run = boot({ max_run_seconds: null, max_tokens: 100 })
  run.respond({ inputTokens: 125 })
  assert.deepEqual(run.exits, [75])
})
