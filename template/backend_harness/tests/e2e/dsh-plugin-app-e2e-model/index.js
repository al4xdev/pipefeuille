/**
 * TEST ONLY, never in the runtime image: an offline stand-in for the model of
 * the example agent `summarizer`, for tests/e2e.sh. Like tests/context.mjs, an
 * `llm/stream` middleware answers before any adapter runs, so the request keeps
 * the profile's real route and no provider is called (the e2e container has no
 * network besides its own). Scripted by how many assistant turns the request
 * already holds:
 *   0  call `read` on style.md (the agent's shared tool, through the fence)
 *   1  call `finalize_summary` with a summary of the note in the first message
 *   2+ a short text (only reached if finalize did not end the run)
 * Each answer carries a usage chunk, so the server's usage sum has something to
 * add, and one structured stderr line, which the server relays.
 *
 * @module dsh-plugin-app-e2e-model
 */

export const name = 'app-e2e-model'

const textOf = message => (Array.isArray(message.content) ? message.content : [])
  .map(block => (block.type === 'text' ? block.text : '')).join('')

// The note the server dispatched: the first user message that parses as {name, text}.
function noteOf(messages) {
  for (const message of messages) {
    if (message.role !== 'user') continue
    try {
      const note = JSON.parse(textOf(message))
      if (note && typeof note.text === 'string') return note
    } catch {}
  }
  return { name: '?', text: '' }
}

function* toolCall(id, tool, args) {
  const json = JSON.stringify(args)
  yield { type: 'block-start', index: 0, blockType: 'tool-call' }
  yield { type: 'tool-call-delta', index: 0, id, name: tool, argumentsDelta: json }
  yield { type: 'block-end', index: 0, block: { type: 'tool-call', id, name: tool, arguments: json } }
}

export function apply(ctx) {
  const dispose = ctx.on('llm/stream', async function* answer(options) {
    if (options.purpose) {
      // A side call (none expected: the profile disables them). Answer empty-handed.
      yield { type: 'finish', reason: { kind: 'stop' } }
      return
    }
    const turns = options.messages.filter(message => message.role === 'assistant').length
    // Did the read of style.md come back with its text (through the workspace fence)?
    const styleRead = JSON.stringify(options.messages).includes('At most three sentences')
    process.stderr.write(`${JSON.stringify({ severity: 'INFO', component: name, event: 'answered', turn: turns, styleRead, provider: options.provider, model: options.model, tools: (options.tools ?? []).map(tool => tool.name) })}\n`)
    if (turns === 0) {
      yield* toolCall('e2e-read', 'read', { file_path: 'style.md' })
    } else if (turns === 1) {
      const note = noteOf(options.messages)
      const words = note.text.split(/\s+/).filter(Boolean).length
      yield* toolCall('e2e-finalize', 'finalize_summary', { summary: `The note ${note.name} has ${words} words.` })
    } else {
      yield { type: 'block-start', index: 0, blockType: 'text' }
      yield { type: 'text-delta', index: 0, text: 'done' }
      yield { type: 'block-end', index: 0, block: { type: 'text', text: 'done' } }
    }
    yield { type: 'usage', usage: { inputTokens: 100, outputTokens: 10, cacheReadTokens: 5 } }
    yield { type: 'finish', reason: { kind: turns < 2 ? 'tool-calls' : 'stop' } }
  })
  ctx.effect(() => dispose, 'app-e2e-model: stop answering')
}
