/**
 * TEST ONLY (test/dsh-boot.sh): a scripted model that drives the two telemetry
 * tools through a real dsh, offline. Like the harness's e2e model, an
 * `llm/stream` middleware answers before any adapter runs, so no provider is
 * called. Scripted by how many assistant turns the request already holds: the
 * calls in PROBES, one per turn, then a short text. dsh records each tool
 * result (and whether it was an error) in the session log, which the test
 * reads back with app-telemetry itself.
 *
 * @module dsh-plugin-app-telemetry-probe
 */

export const name = 'app-telemetry-probe'

// [tool, arguments]. The first two must answer; every other one must be refused.
export const PROBES = [
  ['telemetry_schema', {}],
  ['telemetry_sql', { query: 'SELECT tenant_id, turns FROM sessions ORDER BY tenant_id' }],
  ['telemetry_sql', { query: 'DELETE FROM events' }],
  ['telemetry_sql', { query: "SELECT * FROM read_text('/etc/hostname')" }],
  ['telemetry_sql', { query: "ATTACH ':memory:' AS other" }],
  ['telemetry_sql', { query: 'SET enable_external_access = true' }],
  ['telemetry_sql', { query: 'SELECT 1', cache: '../../../etc/passwd' }],
]

export function apply(ctx) {
  const dispose = ctx.on('llm/stream', async function* answer(options) {
    const turns = options.purpose ? PROBES.length : options.messages.filter(message => message.role === 'assistant').length
    const probe = PROBES[turns]
    if (probe) {
      const [tool, args] = probe
      const id = `probe-${turns}`
      const json = JSON.stringify(args)
      yield { type: 'block-start', index: 0, blockType: 'tool-call' }
      yield { type: 'tool-call-delta', index: 0, id, name: tool, argumentsDelta: json }
      yield { type: 'block-end', index: 0, block: { type: 'tool-call', id, name: tool, arguments: json } }
    } else {
      yield { type: 'block-start', index: 0, blockType: 'text' }
      yield { type: 'text-delta', index: 0, text: 'done' }
      yield { type: 'block-end', index: 0, block: { type: 'text', text: 'done' } }
    }
    yield { type: 'usage', usage: { inputTokens: 10, outputTokens: 1 } }
    yield { type: 'finish', reason: { kind: probe ? 'tool-calls' : 'stop' } }
  })
  ctx.effect(() => dispose, 'app-telemetry-probe: stop answering')
}
