// app-agent's refusals that stop a run before dsh starts. Runs in the harness image, against
// the installed /usr/local/bin/app-agent and the agents as installed:
//
//   backend_harness/tests/test.sh

import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { mkdir, mkdtemp, readdir, rm, symlink, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, beforeEach, test } from 'node:test'

const PID = '33333333-3333-4333-8333-333333333333'
const TENANT = 'apptest'
let tmp

beforeEach(async () => {
  tmp = await mkdtemp(join(tmpdir(), 'app-agent-test-'))
})
afterEach(() => rm(tmp, { recursive: true, force: true }))

const agent = (...args) => {
  const { status, stderr } = spawnSync('app-agent', args, {
    env: { ...process.env, APP_TENANT_ID: TENANT },
    encoding: 'utf8',
  })
  return { status, stderr }
}

test('a template whose links stay inside it passes the check', async () => {
  const template = join(tmp, 'ok', 'workspace')
  await mkdir(join(template, 'docs'), { recursive: true })
  await writeFile(join(template, 'AGENTS.md'), 'x\n')
  await symlink('../AGENTS.md', join(template, 'docs', 'up.md'))
  await symlink('docs', join(template, 'alias'))
  await symlink('missing-but-inside', join(template, 'dangling'))
  assert.deepEqual(agent('check', template), { status: 0, stderr: '' })
})

test('a template link that leaves the template fails the check', async () => {
  const outside = join(tmp, 'outside.csv')
  await writeFile(outside, 'secret\n')
  const cases = {
    'x.csv': outside, // absolute, to a host file
    'up.csv': '../../outside.csv', // relative, climbing out
    'dir': tmp, // a folder outside
    'gone.csv': '/tmp/app-work/other/probe/x.csv', // another tenant's, even if not there yet
    'self': '.', // the template itself, linked into every workspace
  }
  for (const [name, target] of Object.entries(cases)) {
    const template = join(tmp, name.replace('.', '_'), 'workspace')
    await mkdir(join(template, 'deep'), { recursive: true })
    await symlink(target === '.' ? '..' : target, join(template, 'deep', name))
    const { status, stderr } = agent('check', template)
    assert.equal(status, 2, `${name}: ${stderr}`)
    assert.match(stderr, new RegExp(`deep/${name.replace('.', '\\.')} in the template of .* leaves it`), name)
  }
})

test('every installed agent template passes the check', async () => {
  const agents = (await readdir('/opt/app/agents', { withFileTypes: true }))
    .filter(entry => entry.isDirectory() && existsSync(join('/opt/app/agents', entry.name, 'workspace')))
  assert.ok(agents.length > 0)
  for (const { name } of agents) assert.equal(agent('check', `/opt/app/agents/${name}/workspace`).status, 0, name)
})

test('an input starting with - is refused before any workspace exists', () => {
  // dsh re-parses its last argument in the booted app, even after `--`: it would be a flag.
  for (const input of ['-x', '--version', '--help', '-']) {
    const ran = agent('run', 'summarizer', PID, input)
    assert.deepEqual(ran, { status: 2, stderr: "app-agent: the input starts with '-'\n" }, input)
    const resumed = agent('resume', PID, input)
    assert.deepEqual(resumed, { status: 2, stderr: "app-agent: the input starts with '-'\n" }, input)
  }
  assert.equal(existsSync(join('/tmp/app-work', TENANT, 'summarizer', PID)), false)
})
