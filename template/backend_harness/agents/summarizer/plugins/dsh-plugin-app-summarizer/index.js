/**
 * summarizer's own plugin: `finalize_summary`, the one way that agent ends a
 * run. The model hands over the summary as a structured argument; the tool
 * checks it (summary.js, the rules of workspace/style.md) and, when it passes,
 * makes it the run's output and concludes the turn.
 *
 * The run's output is what headless dsh writes to stdout: the last assistant
 * text of the turn. A concluded turn may carry no text, or stray text next to
 * the call, so the tool writes the JSON itself and silences stdout after it.
 *
 * Which agent it serves is the harness's business: the image build inserts
 * every folder of agents/summarizer/plugins into that agent's own profile
 * (app_summarizer) and no other, so the plugin registers unconditionally.
 *
 * @module dsh-plugin-app-summarizer
 */

import { defineTool } from '@deepseek-ai/dsh-tools'
import { problemsOf } from './summary.js'

export const name = 'app-summarizer'
export const inject = ['tools']

// From here on nothing else reaches stdout, so the process output is exactly
// one JSON line. A callback still runs, so no writer waits forever.
function ownStdout(line) {
  process.stdout.write(line)
  process.stdout.write = (_chunk, encoding, callback) => {
    const done = typeof encoding === 'function' ? encoding : callback
    if (typeof done === 'function') queueMicrotask(() => done())
    return true
  }
}

export function apply(ctx) {
  let finalized = false

  ctx.tools.register(defineTool({
    name: 'finalize_summary',
    description: 'Hand over the summary of the note and end the run. Call it once. If it reports problems, nothing was handed over: fix them and call it again.',
    parameters: {
      summary: { type: 'string', required: true, description: 'The summary, following style.md.' },
    },
    output: {
      schema: { type: 'string' },
      render: (_args, value) => [{ type: 'text', text: value }],
    },
    async execute(args, exec) {
      if (finalized) throw new Error('The summary was already handed over; the run is over.')
      const problems = problemsOf(args.summary)
      if (problems.length > 0) {
        throw new Error(`Nothing was handed over. Fix these and call finalize_summary again:\n- ${problems.join('\n- ')}`)
      }
      finalized = true
      ownStdout(`${JSON.stringify({ summary: args.summary.trim() })}\n`)
      exec.concludeTurn()
      return 'Handed over the summary.'
    },
  }))
}
