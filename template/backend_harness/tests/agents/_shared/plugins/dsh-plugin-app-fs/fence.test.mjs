// dsh-plugin-app-fs against a real temp tree: one workspace of tenant t1, a
// sibling tenant t2, the server's <pid>.out, a file outside, and the template.
// Runs in the harness image, against the plugins as installed there:
//
//   backend_harness/tests/test.sh

import assert from 'node:assert/strict'
import { lstat, mkdir, mkdtemp, readFile, readlink, rm, symlink, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, beforeEach, test } from 'node:test'

const plugin = new URL('dsh-plugin-app-fs/', `file://${process.env.APP_PLUGINS ?? '/opt/dsh/node_modules/'}`)
const { openWorkspace, MAX_FILE_BYTES } = await import(new URL('workspace.js', plugin))
const files = await import(new URL('files.js', plugin))
const { applyPatch, undoPatch } = await import(new URL('patch.js', plugin))
const { guidance } = await import(new URL('tools.js', plugin))

const PID = '11111111-1111-4111-8111-111111111111'
const SIBLING_PID = '22222222-2222-4222-8222-222222222222'
let tmp, work, agents, root, sibling, outside, template, ws, obs

beforeEach(async () => {
  tmp = await mkdtemp(join(tmpdir(), 'app-fs-test-'))
  work = join(tmp, 'app-work')
  agents = join(tmp, 'agents')
  template = join(agents, 'probe', 'workspace')
  await mkdir(join(template, '.agents'), { recursive: true })
  await writeFile(join(template, 'AGENTS.md'), 'be careful\n')
  await writeFile(join(template, '.agents', 'skill.md'), 'skill\n')
  root = join(work, 't1', 'probe', PID)
  await mkdir(root, { recursive: true })
  await symlink(join(template, 'AGENTS.md'), join(root, 'AGENTS.md'))
  await symlink(join(template, '.agents'), join(root, '.agents'))
  sibling = join(work, 't2', 'probe', SIBLING_PID)
  await mkdir(sibling, { recursive: true })
  await writeFile(join(sibling, 'secret.txt'), 'tenant t2\n')
  await writeFile(join(work, 't1', `${PID}.out`), 'answer\n')
  outside = join(tmp, 'outside')
  await mkdir(outside)
  await writeFile(join(outside, 'x.txt'), 'outside\n')
  ws = await openWorkspace(root, { env: { APP_TENANT_ID: 't1' }, work, agents })
  obs = new files.Observations()
})

afterEach(() => rm(tmp, { recursive: true, force: true }))

// The fence may echo the path the model typed; any other host path is a leak.
const code = (expected, given = '') => error => {
  assert.equal(error.code ?? error.cause?.code, expected, error.message)
  assert.ok(!error.message.replaceAll(given, '').includes(tmp), `leaks a host path: ${error.message}`)
  return true
}
const exists = path => lstat(path).then(() => true, () => false)

const escapes = () => [
  '../x',
  'a/../../x',
  `../../../t2/probe/${SIBLING_PID}/secret.txt`,
  join(sibling, 'secret.txt'),
  `../../${PID}.out`,
  join(outside, 'x.txt'),
  '/etc/passwd',
  '/proc/self/root/etc/passwd',
  '/proc/self/cwd/x',
]

test('every escape reads like a missing file', async () => {
  for (const path of escapes()) {
    await assert.rejects(files.read(ws, obs, { file_path: path }), code('APP_FS_NOT_FOUND', path), path)
    await assert.rejects(files.list(ws, { path }), code('APP_FS_NOT_FOUND', path), path)
  }
})

test('no escape writes, edits, patches or trashes anything', async () => {
  for (const path of escapes()) {
    await assert.rejects(files.write(ws, obs, { file_path: path, content: 'pwned\n' }), code('APP_FS_NOT_FOUND', path), path)
    await assert.rejects(files.edit(ws, obs, { file_path: path, old_string: 'a', new_string: 'b' }), code('APP_FS_NOT_FOUND', path), path)
    await assert.rejects(applyPatch(ws, obs, new Map(), `*** Begin Patch\n*** Add File: ${path}\n+pwned\n*** End Patch`), code('APP_FS_NOT_FOUND', path), path)
    const result = JSON.parse(await files.trash(ws, obs, { paths: [path] }))
    assert.equal(result.results[0].status, 'not_moved', path)
  }
  // Not an escape: a literal file name, written inside the workspace.
  await files.write(ws, obs, { file_path: '..%2fsecret.txt', content: 'x\n' })
  assert.equal(await readFile(join(root, '..%2fsecret.txt'), 'utf8'), 'x\n')
  assert.equal(await readFile(join(sibling, 'secret.txt'), 'utf8'), 'tenant t2\n')
  assert.equal(await readFile(join(outside, 'x.txt'), 'utf8'), 'outside\n')
  assert.equal(await readFile(join(work, 't1', `${PID}.out`), 'utf8'), 'answer\n')
  assert.equal(await exists(join(work, 't1', 'x')), false)
})

test('a move out of the workspace is refused before anything is written', async () => {
  await files.write(ws, obs, { file_path: 'a.txt', content: 'a\n' })
  await files.read(ws, obs, { file_path: 'a.txt' })
  const patch = `*** Begin Patch\n*** Update File: a.txt\n*** Move to: ../../../t2/probe/${SIBLING_PID}/a.txt\n*** End Patch`
  await assert.rejects(applyPatch(ws, obs, new Map(), patch), code('APP_FS_NOT_FOUND'))
  assert.equal(await readFile(join(root, 'a.txt'), 'utf8'), 'a\n')
  assert.equal(await exists(join(sibling, 'a.txt')), false)
})

test('links that leave the workspace are never followed', async () => {
  // The agent cannot make links (no shell); these stand in for a mistake of ours.
  await symlink(outside, join(root, 'out'))
  await symlink(sibling, join(root, 'sib'))
  await symlink('loop', join(root, 'loop'))
  for (const path of ['out/x.txt', 'sib/secret.txt', 'loop', 'loop/x']) {
    await assert.rejects(files.read(ws, obs, { file_path: path }), code('APP_FS_NOT_FOUND'), path)
  }
  await assert.rejects(files.write(ws, obs, { file_path: 'out/new.txt', content: 'x' }), code('APP_FS_READ_ONLY'))
  await assert.rejects(files.write(ws, obs, { file_path: 'sib/secret.txt', content: 'x' }), code('APP_FS_READ_ONLY'))
  const listing = await files.list(ws, { depth: 3 })
  assert.match(listing, /^out$/m)
  assert.doesNotMatch(listing, /x\.txt|secret/)
  // trash moves the link itself; its target stays.
  const moved = JSON.parse(await files.trash(ws, obs, { paths: ['out'] })).results[0]
  assert.equal(moved.status, 'moved')
  assert.equal(await readlink(join(root, moved.recovery)), outside)
  assert.equal(await readFile(join(outside, 'x.txt'), 'utf8'), 'outside\n')
})

test('the template is readable and never changed', async () => {
  assert.match(await files.read(ws, obs, { file_path: 'AGENTS.md' }), /1: be careful/)
  assert.match(await files.read(ws, obs, { file_path: '.agents/skill.md' }), /1: skill/)
  assert.match(await files.list(ws, { depth: 2 }), /^\.agents\/skill\.md$/m)
  await assert.rejects(files.write(ws, obs, { file_path: 'AGENTS.md', content: 'x' }), code('APP_FS_READ_ONLY'))
  await assert.rejects(files.edit(ws, obs, { file_path: 'AGENTS.md', old_string: 'careful', new_string: 'reckless' }), code('APP_FS_READ_ONLY'))
  await assert.rejects(files.write(ws, obs, { file_path: '.agents/new.md', content: 'x' }), code('APP_FS_READ_ONLY'))
  await assert.rejects(applyPatch(ws, obs, new Map(), '*** Begin Patch\n*** Update File: AGENTS.md\n@@\n-be careful\n+be reckless\n*** End Patch'), code('APP_FS_READ_ONLY'))
  await assert.rejects(applyPatch(ws, obs, new Map(), '*** Begin Patch\n*** Delete File: .agents/skill.md\n*** End Patch'), code('APP_FS_READ_ONLY'))
  assert.equal(JSON.parse(await files.trash(ws, obs, { paths: ['.agents/skill.md'] })).results[0].status, 'not_moved')
  assert.equal(JSON.parse(await files.trash(ws, obs, { paths: ['AGENTS.md'] })).results[0].status, 'moved')
  assert.equal(await readFile(join(template, 'AGENTS.md'), 'utf8'), 'be careful\n')
  assert.equal(await readFile(join(template, '.agents', 'skill.md'), 'utf8'), 'skill\n')
})

test('malformed paths are refused; unicode is fine', async () => {
  for (const path of ['', '   ', 'a\0b', 'a\nb', 'x'.repeat(5000)]) {
    await assert.rejects(files.write(ws, obs, { file_path: path, content: 'x' }), code('APP_FS_BAD_PATH'), JSON.stringify(path.slice(0, 10)))
  }
  await assert.rejects(files.write(ws, obs, { file_path: '.', content: 'x' }), code('APP_FS_ROOT'))
  assert.match(await files.write(ws, obs, { file_path: 'notas/ação.md', content: 'olá\n' }), /<path>notas\/ação\.md<\/path>/)
  assert.match(await files.read(ws, obs, { file_path: 'notas/ação.md' }), /1: olá/)
})

test('changes need a read at the current version', async () => {
  await files.write(ws, obs, { file_path: 'a.txt', content: 'one\n' })
  const fresh = new files.Observations()
  await assert.rejects(files.write(ws, fresh, { file_path: 'a.txt', content: 'x' }), code('APP_FS_NOT_OBSERVED'))
  await assert.rejects(files.edit(ws, fresh, { file_path: 'a.txt', old_string: 'one', new_string: 'two' }), code('APP_FS_NOT_OBSERVED'))
  await files.read(ws, fresh, { file_path: 'a.txt' })
  await writeFile(join(root, 'a.txt'), 'changed behind its back\n')
  await assert.rejects(files.edit(ws, fresh, { file_path: 'a.txt', old_string: 'changed', new_string: 'x' }), code('APP_FS_STALE'))
  await files.read(ws, fresh, { file_path: 'a.txt' })
  await files.edit(ws, fresh, { file_path: 'a.txt', old_string: 'behind', new_string: '$& in front of' })
  assert.equal(await readFile(join(root, 'a.txt'), 'utf8'), 'changed $& in front of its back\n')
})

test('file and workspace quotas hold, patches included', async () => {
  const big = 'x'.repeat(MAX_FILE_BYTES + 1)
  await assert.rejects(files.write(ws, obs, { file_path: 'big.txt', content: big }), code('APP_FS_TOO_LARGE'))
  await assert.rejects(applyPatch(ws, obs, new Map(), `*** Begin Patch\n*** Add File: big.txt\n+${big}\n*** End Patch`), code('APP_FS_TOO_LARGE'))
  const chunk = 'y'.repeat(15 * 1024 * 1024)
  for (let i = 0; i < 4; i++) await files.write(ws, obs, { file_path: `c${i}.txt`, content: chunk })
  await assert.rejects(files.write(ws, obs, { file_path: 'c4.txt', content: chunk }), code('APP_FS_QUOTA'))
  await assert.rejects(applyPatch(ws, obs, new Map(), `*** Begin Patch\n*** Add File: c4.txt\n+${chunk}\n*** End Patch`), code('APP_FS_QUOTA'))
  assert.equal(await exists(join(root, 'c4.txt')), false)
})

test('trash keeps files recoverable and protects itself', async () => {
  await files.write(ws, obs, { file_path: 'notes/a.txt', content: 'keep me\n' })
  const moved = JSON.parse(await files.trash(ws, obs, { paths: ['notes'] })).results[0]
  assert.equal(moved.status, 'moved')
  assert.match(moved.recovery, /^\.dumps\/\.trash\/.+-notes$/)
  assert.equal(await readFile(join(root, moved.recovery, 'a.txt'), 'utf8'), 'keep me\n')
  for (const path of ['.', '.dumps', '.dumps/.trash', moved.recovery]) {
    assert.equal(JSON.parse(await files.trash(ws, obs, { paths: [path] })).results[0].status, 'not_moved', path)
  }
})

test('apply_patch updates read lines, and undo restores this process\'s receipts only', async () => {
  await files.write(ws, obs, { file_path: 'a.txt', content: '1\n2\n3\n' })
  const fresh = new files.Observations()
  await files.read(ws, fresh, { file_path: 'a.txt', offset: 3 })
  const patch = '*** Begin Patch\n*** Update File: a.txt\n@@\n 1\n-2\n+two\n*** End Patch'
  await assert.rejects(applyPatch(ws, fresh, new Map(), patch), code('APP_FS_NOT_OBSERVED'))
  await files.read(ws, fresh, { file_path: 'a.txt' })
  const receipts = new Map()
  const receipt = JSON.parse(await applyPatch(ws, fresh, receipts, patch))
  assert.equal(receipt.status, 'applied')
  assert.match(receipt.manifest, /^\.dumps\/\.patch\/.+\/manifest\.json$/)
  assert.equal(await readFile(join(root, 'a.txt'), 'utf8'), '1\ntwo\n3\n')
  await assert.rejects(undoPatch(ws, fresh, new Map(), receipt.manifest), /Unknown recovery receipt/)
  assert.equal(JSON.parse(await undoPatch(ws, fresh, receipts, receipt.manifest)).status, 'undone')
  assert.equal(await readFile(join(root, 'a.txt'), 'utf8'), '1\n2\n3\n')
})

test('the workspace fails closed', async () => {
  const open = (cwd, tenant = 't1') => openWorkspace(cwd, { env: { APP_TENANT_ID: tenant }, work, agents })
  await assert.rejects(open(root, 't2'), code('APP_FS_NO_WORKSPACE'))
  await assert.rejects(open(root, null), code('APP_FS_NO_WORKSPACE'))
  await assert.rejects(open(join(root, 'sub')), code('APP_FS_NO_WORKSPACE'))
  await assert.rejects(open(join(work, 't1', 'probe')), code('APP_FS_NO_WORKSPACE'))
  await assert.rejects(open(undefined), code('APP_FS_NO_WORKSPACE'))
  const linked = join(work, 't1', 'probe', '33333333-3333-4333-8333-333333333333')
  await symlink(sibling, linked)
  await assert.rejects(open(linked), code('APP_FS_NO_WORKSPACE'))
})

test('the guidance follows the selected tools', () => {
  assert.equal(guidance(new Set()), '')
  assert.doesNotMatch(guidance(new Set(['read'])), /trash|\.dumps/)
  assert.match(guidance(new Set(['read', 'write', 'trash'])), /\.dumps\/[\s\S]*trash/)
  // "final message, not a file" only where the agent could write its answer to one.
  assert.doesNotMatch(guidance(new Set(['read'])), /final message/)
  assert.match(guidance(new Set(['read', 'write'])), /final message, not a file/)
})

// Critic findings (fence review): each one a regression test.

test('names past NAME_MAX are refused, and errors kept in results carry no host path', async () => {
  const long = 'a'.repeat(260)
  await assert.rejects(files.read(ws, obs, { file_path: long }), code('APP_FS_BAD_PATH'))
  const out = await files.trash(ws, obs, { paths: [long] })
  assert.ok(!out.includes(tmp), out)
  // 230 bytes fits on disk, but not with the trash prefix: the trash name is cut.
  const name = 'b'.repeat(230)
  const receipt = JSON.parse(await applyPatch(ws, obs, new Map(), `*** Begin Patch\n*** Add File: ${name}\n+hi\n*** End Patch`))
  const receipts = new Map([[receipt.manifest, receipt]])
  const undone = await undoPatch(ws, obs, receipts, receipt.manifest)
  assert.ok(!undone.includes(tmp), undone)
  assert.equal(JSON.parse(undone).status, 'undone')
  assert.equal(await exists(join(root, name)), false)
})

test('a patch may not touch a path and its child', async () => {
  const receipts = new Map()
  await assert.rejects(applyPatch(ws, obs, receipts, '*** Begin Patch\n*** Add File: a\n+x\n*** Add File: a/b\n+y\n*** End Patch'), /overlap/)
  assert.equal(await exists(join(root, 'a')), false)
  assert.equal(await exists(join(root, '.dumps')), false)
})

test('missing parent folders count against the entries quota', async () => {
  const deep = i => `d${i}/${Array.from({ length: 900 }, () => 'p').join('/')}/f.txt`
  const ops = Array.from({ length: 12 }, (_, i) => `*** Add File: ${deep(i)}\n+x`).join('\n')
  await assert.rejects(applyPatch(ws, obs, new Map(), `*** Begin Patch\n${ops}\n*** End Patch`), code('APP_FS_QUOTA'))
  assert.equal(await exists(join(root, 'd0')), false)
})

test('.dumps, its trash and patch receipts cannot be changed directly', async () => {
  for (const path of ['.dumps', '.dumps/.trash', '.dumps/.trash/x', '.dumps/.patch/x/0.original']) {
    await assert.rejects(files.write(ws, obs, { file_path: path, content: 'x' }), code('APP_FS_PROTECTED'), path)
  }
  await assert.rejects(applyPatch(ws, obs, new Map(), '*** Begin Patch\n*** Add File: .dumps/.patch/y\n+x\n*** End Patch'), code('APP_FS_PROTECTED'))
  await files.write(ws, obs, { file_path: '.dumps/notes.md', content: 'scratch\n' })
  const out = JSON.parse(await files.trash(ws, obs, { paths: ['.dumps/notes.md', '.dumps/.patch', '.dumps'] }))
  assert.deepEqual(out.results.map(r => r.status), ['moved', 'not_moved', 'not_moved'])
})

test('read coverage: full reads count, partial reads do not cover whole-file changes', async () => {
  await writeFile(join(root, 'marker.txt'), `const s = "... (line truncated to "\n${'z'.repeat(3000)}\n`)
  await files.read(ws, obs, { file_path: 'marker.txt' })
  await applyPatch(ws, obs, new Map(), '*** Begin Patch\n*** Delete File: marker.txt\n*** End Patch')
  assert.equal(await exists(join(root, 'marker.txt')), false)

  await writeFile(join(root, 'long.txt'), 'one\ntwo\nthree\n')
  await files.read(ws, obs, { file_path: 'long.txt', limit: 1 })
  await assert.rejects(files.write(ws, obs, { file_path: 'long.txt', content: 'gone\n' }), code('APP_FS_NOT_OBSERVED'))
  await assert.rejects(files.edit(ws, obs, { file_path: 'long.txt', old_string: 'three', new_string: '3' }), code('APP_FS_NOT_OBSERVED'))
  await files.edit(ws, obs, { file_path: 'long.txt', old_string: 'one', new_string: '1' })
  // A file this process wrote stays fully known after a partial re-read.
  await files.read(ws, obs, { file_path: 'long.txt', limit: 1 })
  await files.write(ws, obs, { file_path: 'long.txt', content: 'all new\n' })
})