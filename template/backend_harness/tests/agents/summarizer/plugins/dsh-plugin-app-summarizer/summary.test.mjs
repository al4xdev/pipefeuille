// dsh-plugin-app-summarizer (the example agent's own plugin): the admission
// rules and finalize_summary as dsh calls it. Runs in the harness image:
//
//   backend_harness/tests/test.sh
import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { test } from 'node:test'

const PLUGIN = '/opt/dsh/node_modules/dsh-plugin-app-summarizer/'
const { problemsOf, MAX_CHARS } = await import(`${PLUGIN}summary.js`)

test('a summary is non-empty plain prose of at most three sentences and 600 characters', () => {
  assert.deepEqual(problemsOf('The note lists three tasks. Two are done.'), [])
  assert.deepEqual(problemsOf(''), ['the summary is empty'])
  assert.deepEqual(problemsOf('   '), ['the summary is empty'])
  assert.deepEqual(problemsOf(undefined), ['the summary is empty'])
  assert.deepEqual(problemsOf('One. Two. Three. Four.'), ['the summary has 4 sentences; at most 3'])
  assert.deepEqual(problemsOf('x'.repeat(MAX_CHARS + 1)), [`the summary has ${MAX_CHARS + 1} characters; at most ${MAX_CHARS}`])
  assert.deepEqual(problemsOf('# Title\nText.'), ['the summary is plain prose: no headings or list items'])
  assert.deepEqual(problemsOf('- item one'), ['the summary is plain prose: no headings or list items'])
  // A version number or a decimal is no sentence end.
  assert.deepEqual(problemsOf('Version 2.5 ships on 1.3.2027 with 3 fixes.'), [])
})

// The tool, registered on a fake ctx in a child process: an accepted summary
// takes over stdout, so it must not be this test runner's.
function finalize(calls) {
  const script = `
    const { apply } = await import(${JSON.stringify(`${PLUGIN}index.js`)})
    let tool
    apply({ tools: { register: definition => { tool = definition } } })
    let concluded = 0
    for (const summary of ${JSON.stringify(calls)}) {
      try {
        const result = await tool.execute({ summary }, { concludeTurn: () => { concluded += 1 } })
        process.stderr.write('ok:' + result + '\\n')
      } catch (error) {
        process.stderr.write('error:' + error.message.split('\\n')[0] + '\\n')
      }
    }
    process.stdout.write('after the handover\\n')
    process.stderr.write('concluded:' + concluded + '\\n')
  `
  const result = spawnSync(process.execPath, ['--input-type=module', '-e', script], { encoding: 'utf8' })
  assert.equal(result.status, 0, result.stderr)
  return { stdout: result.stdout, stderr: result.stderr.trim().split('\n') }
}

test('finalize_summary hands over one JSON line, concludes the turn, and refuses a second call', () => {
  const { stdout, stderr } = finalize(['', '  A short summary.  ', 'Another one.'])
  assert.equal(stdout, '{"summary":"A short summary."}\n')
  assert.deepEqual(stderr, [
    'error:Nothing was handed over. Fix these and call finalize_summary again:',
    'ok:Handed over the summary.',
    'error:The summary was already handed over; the run is over.',
    'concluded:1',
  ])
})
