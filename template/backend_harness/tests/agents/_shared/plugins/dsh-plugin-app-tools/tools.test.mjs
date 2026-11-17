// dsh-plugin-app-tools: the list, the agent.yml reader, APP_TOOLS, and the CLI
// app-agent runs. Runs in the harness image:
//
//   backend_harness/tests/test.sh

import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { cp, mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { test } from 'node:test'

const plugin = new URL('dsh-plugin-app-tools/', `file://${process.env.APP_PLUGINS ?? '/opt/dsh/node_modules/'}`)
const { KNOWN, pluginOf, selectTools, toolsOf } = await import(new URL('index.js', plugin))
const { parseAgent } = await import(new URL('agent.js', plugin))
const CLI = fileURLToPath(new URL('cli.js', plugin))
const LIMITS = 'limits:\n  max_run_seconds: null\n  max_tokens: null\n  max_attempts: 3\n'
const HEAD = `description: An agent.\n${LIMITS}`

test('the names come from the shared plugins\' package.json (harness.tools)', async () => {
  const declared = async name => JSON.parse(await readFile(fileURLToPath(new URL(`../${name}/package.json`, plugin)), 'utf8')).harness.tools
  assert.deepEqual(toolsOf('dsh-plugin-app-fs'), await declared('dsh-plugin-app-fs'))
  assert.deepEqual(toolsOf('dsh-plugin-app-sql'), await declared('dsh-plugin-app-sql'))
  // Today's set and order; a new opt-in tool shows up here first.
  assert.deepEqual(KNOWN, ['read', 'write', 'edit', 'list', 'trash', 'apply_patch', 'sql'])
  assert.equal(pluginOf('apply_patch'), 'dsh-plugin-app-fs')
  assert.equal(pluginOf('sql'), 'dsh-plugin-app-sql')
  assert.equal(pluginOf('finalize_summary'), undefined)
  assert.deepEqual(toolsOf('dsh-plugin-app-summarizer'), [])
})

test('a bad declaration fails at import', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'app-tools-decl-'))
  try {
    const copy = join(dir, 'dsh-plugin-app-tools')
    await cp(fileURLToPath(plugin), copy, { recursive: true })
    const declare = async (name, app) => {
      await mkdir(join(dir, name), { recursive: true })
      await writeFile(join(dir, name, 'package.json'), JSON.stringify({ name, harness: app }))
    }
    let n = 0
    // A fresh URL per import: the module reads the declarations once, at load.
    const load = () => import(`${pathToFileURL(join(copy, 'index.js')).href}?${n++}`)
    await declare('dsh-plugin-a', { tools: ['alpha'] })
    await declare('not-a-plugin', { tools: ['ignored'] })
    assert.deepEqual((await load()).KNOWN, ['alpha'])
    await declare('dsh-plugin-b', { tools: ['alpha'] })
    await assert.rejects(load(), /tool alpha declared by both dsh-plugin-a and dsh-plugin-b/)
    await declare('dsh-plugin-b', { tools: ['Bad-Name'] })
    await assert.rejects(load(), /bad tool name/)
    await declare('dsh-plugin-b', { tools: [] })
    await assert.rejects(load(), /non-empty list/)
  } finally {
    await rm(dir, { recursive: true, force: true })
  }
})

test('agent.yml: a description, the limits, and the tools', () => {
  const { agent, error } = parseAgent(`# comment\n${HEAD}tools:\n  shared: [read, edit, list] # inline\n  own:\n    x_tool:\n      effects:\n        writes: w\n        model: m\n      repeat:\n        fails: f\n`)
  assert.equal(error, undefined)
  assert.equal(agent.description, 'An agent.')
  assert.deepEqual(agent.limits, { max_run_seconds: null, max_tokens: null, max_attempts: 3 })
  assert.deepEqual([...agent.shared], ['read', 'edit', 'list'])
  assert.deepEqual(agent.own, ['x_tool'])
  const bare = parseAgent(`description: An agent. It rests.\nlimits:\n  max_run_seconds: 600\n  max_tokens: 200000\n  max_attempts: 1\n`)
  assert.equal(bare.error, undefined)
  assert.equal(bare.agent.shared.size, 0)
  assert.deepEqual(bare.agent.own, [])
})

test('agent.yml refuses what it does not know, and bad values', () => {
  const own = (effects, repeat) => `${HEAD}tools:\n  own:\n    x_tool:\n      effects: ${effects}\n      repeat: ${repeat}\n`
  const cases = [
    ['', /not a mapping/],
    [`${HEAD}description: e\n`, /duplicated mapping key/],
    [`${HEAD}tools:\n  shared: [read]\n  shared: [list]\n`, /duplicated mapping key/],
    [`${HEAD}summary: s\n`, /unknown key summary/],
    [`description: ''\n${LIMITS}`, /description/],
    [`description: an agent\n${LIMITS}`, /description: one or two sentences/],
    [`description: One. Two. Three.\n${LIMITS}`, /description: one or two sentences/],
    [`description: An agent.\n`, /limits: required/],
    [`description: An agent.\nlimits:\n  max_run_seconds: null\n  max_attempts: 3\n`, /limits\.max_tokens: required/],
    [`${HEAD}  retries: 2\n`, /limits: unknown key retries/],
    [HEAD.replace('max_run_seconds: null', 'max_run_seconds: 1.5'), /max_run_seconds: a positive integer, or null/],
    [HEAD.replace('max_run_seconds: null', 'max_run_seconds: true'), /max_run_seconds: a positive integer/],
    [HEAD.replace('max_attempts: 3', 'max_attempts: null'), /max_attempts: a positive integer$/],
    [HEAD.replace('max_attempts: 3', 'max_attempts: 0'), /max_attempts: a positive integer$/],
    [HEAD.replace('max_attempts: 3', "max_attempts: '3'"), /max_attempts: a positive integer$/],
    [`${HEAD}tools: {}\n`, /tools: a mapping/],
    [`${HEAD}tools:\n  shared: []\n`, /non-empty list/],
    [`${HEAD}tools:\n  shared: [read, read]\n`, /listed twice/],
    [`${HEAD}tools:\n  shared: [bash]\n`, /unknown tools: bash/],
    [`${HEAD}tools:\n  shared: [apply_patch]\n`, /apply_patch need read/],
    [`${HEAD}tools:\n  own: {}\n`, /tools\.own: a mapping/],
    [own('writes', '{fails: f}'), /effects: a mapping of value to note/],
    [own('{writes: ""}', '{fails: f}'), /effects\.writes: the note/],
    [own('{writes: w}', '{fails: f, safe: s}'), /repeat: exactly one value/],
    [`${HEAD}tools:\n  own:\n    x_tool:\n      effects: {writes: w}\n      repeat: {fails: f}\n      ends_run: true\n`, /unknown key ends_run/],
    [`${HEAD}tools:\n  own:\n    Bad-Name:\n      effects: {writes: w}\n      repeat: {fails: f}\n`, /a tool name is/],
  ]
  for (const [text, pattern] of cases) {
    const { agent, error } = parseAgent(text)
    assert.equal(agent, undefined, text)
    assert.match(error, pattern, text)
  }
})

test('APP_TOOLS selects tools and fails closed', () => {
  assert.deepEqual([...selectTools('read,write').tools], ['read', 'write'])
  assert.equal(selectTools(undefined).tools.size, 0)
  assert.equal(selectTools('').tools.size, 0)
  for (const bad of ['read,bash', 'edit', 'apply_patch,write', 'mock_tool']) {
    const { tools, error } = selectTools(bad)
    assert.equal(tools.size, 0, bad)
    assert.ok(error, bad)
  }
  assert.deepEqual([...selectTools(KNOWN.join(',')).tools], KNOWN)
})

test('the CLI prints APP_TOOLS, nothing without shared tools, and exits 2 on a bad or missing agent.yml', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'app-tools-test-'))
  try {
    const run = file => spawnSync(process.execPath, [CLI, file], { encoding: 'utf8' })
    await writeFile(join(dir, 'good'), `${HEAD}tools:\n  shared: [read, edit, list]\n`)
    assert.deepEqual([run(join(dir, 'good')).status, run(join(dir, 'good')).stdout], [0, 'read,edit,list'])
    await writeFile(join(dir, 'none'), HEAD)
    assert.deepEqual([run(join(dir, 'none')).status, run(join(dir, 'none')).stdout], [0, ''])
    const missing = run(join(dir, 'missing'))
    assert.equal(missing.status, 2)
    assert.match(missing.stderr, /missing.*agent\.yml/)
    await writeFile(join(dir, 'typo'), `${HEAD}tools:\n  shared: [raed]\n`)
    const typo = run(join(dir, 'typo'))
    assert.equal(typo.status, 2)
    assert.match(typo.stderr, /typo: tools\.shared: unknown tools: raed/)
    await writeFile(join(dir, 'orphan'), `${HEAD}tools:\n  shared: [edit]\n`)
    assert.equal(run(join(dir, 'orphan')).status, 2)
    // `limits`: APP_LIMITS, the limits as JSON, from the same parser.
    const limits = (file, ...args) => spawnSync(process.execPath, [CLI, file, ...args], { encoding: 'utf8' })
    await writeFile(join(dir, 'limited'), HEAD.replace('max_run_seconds: null', 'max_run_seconds: 600'))
    assert.deepEqual([limits(join(dir, 'limited'), 'limits').status, JSON.parse(limits(join(dir, 'limited'), 'limits').stdout)],
      [0, { max_run_seconds: 600, max_tokens: null, max_attempts: 3 }])
    assert.equal(limits(join(dir, 'limited'), 'tools').stdout, '')
    assert.equal(limits(join(dir, 'typo'), 'limits').status, 2)
    const unknown = limits(join(dir, 'limited'), 'budget')
    assert.equal(unknown.status, 2)
    assert.match(unknown.stderr, /usage/)
  } finally {
    await rm(dir, { recursive: true, force: true })
  }
})
// The cases every reader of agent.yml is held to (tests/agent_yml_cases.json): this one, the
// image's, gives the verdict the case pins for agent_js (by default, the Python gate's).
// tests/gates/test_agent_yml.py holds the two Python readers to the same file.
test('agent.yml: agent.js gives every shared case the verdict it pins', async () => {
  const file = new URL('../../../../agent_yml_cases.json', import.meta.url)
  const { cases } = JSON.parse(await readFile(file, 'utf8'))
  assert.ok(cases.length > 0)
  for (const { id, text, problems, agent_js: pinned } of cases) {
    const expected = pinned ?? (problems.length ? 'refuses' : 'accepts')
    const { error } = parseAgent(text)
    assert.equal(error === undefined ? 'accepts' : 'refuses', expected, `${id}: ${error ?? 'accepted'}`)
  }
})
