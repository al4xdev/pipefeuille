// The per-agent dsh profiles (app_<name>) the image build generates with
// runtime/bin/app-profiles.mjs, and the generator's refusals. Runs in the
// harness image:
//
//   backend_harness/tests/test.sh
import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { cp, mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { test } from 'node:test'

const AGENTS = '/opt/app/agents'
const PROFILES = join(process.env.DSH_HOME ?? '/home/node/.dsh', 'profiles')
const GENERATOR = '/opt/app/bin/app-profiles.mjs'
// The limits the build hands the harness server (app-profiles.mjs --agents-json).
const AGENTS_JSON = '/opt/app/server/agents.json'
const ANCHOR = '/opt/dsh/node_modules/@deepseek-ai/dsh/package.json'
const { pluginOf } = await import('/opt/dsh/node_modules/dsh-plugin-app-tools/index.js')
const { readAgent } = await import('/opt/dsh/node_modules/dsh-plugin-app-tools/agent.js')
const boot = await import(pathToFileURL(createRequire(ANCHOR).resolve('@deepseek-ai/dsh-app-boot')).href)

const agents = readdirSync(AGENTS).filter(name => existsSync(join(AGENTS, name, 'workspace'))).sort()
const toolsOf = name => {
  const { agent, error } = readAgent(join(AGENTS, name, 'agent.yml'))
  assert.equal(error, undefined, name)
  return [...agent.shared]
}
const expectedPlugins = name => [
  ...[...new Set(toolsOf(name).map(pluginOf))].sort(),
  ...(existsSync(join(AGENTS, name, 'plugins')) ? readdirSync(join(AGENTS, name, 'plugins')).sort() : []),
]
// The profile as dsh composes it (bundles, then cordis.patch.yml): entry ids in order.
const composed = profile => {
  const loaded = boot.loadProfileDirectory('app-test', join(PROFILES, profile), ANCHOR)
  return boot.composeEntries([...loaded.layers.map(layer => layer.patches), loaded.patches]).map(entry => entry.id)
}
// The ids our patch files insert (app-*), in composed order.
const ours = profile => composed(profile).filter(id => id?.startsWith('app-'))
// The agent-default-model config dsh composes for a profile (the last entry with that id wins).
const defaultModel = profile => {
  const loaded = boot.loadProfileDirectory('app-test', join(PROFILES, profile), ANCHOR)
  return boot.composeEntries([...loaded.layers.map(layer => layer.patches), loaded.patches])
    .filter(entry => entry.id === 'agent-default-model').at(-1)?.config
}
// The base's agent-default-model entry with an agent.yml model written in (app-profiles.mjs).
const withModel = (tail, name, model) => model === null ? tail : tail
  .replace(/^ {4}model: .*$/m, `    model: ${model.name}  # agents/${name}/agent.yml`)
  .replace(/^ {4}reasoningEffort: .*$/m, `    reasoningEffort: ${model.reasoning}  # agents/${name}/agent.yml`)

test('every agent has a profile app_<name>, and nothing else does', () => {
  assert.ok(agents.includes('summarizer'), agents.join(', '))
  const generated = readdirSync(PROFILES).filter(name => name.startsWith('app_')).sort()
  assert.deepEqual(generated, agents.map(name => `app_${name}`))
})

test('the base profile app inserts only the runtime plugins', () => {
  assert.deepEqual(ours('app'), ['app-recovery', 'app-limits'])
})

test('an agent profile is app plus its plugins, inserted right before agent-default-model', async () => {
  const base = await readFile(join(PROFILES, 'app', 'cordis.patch.yml'), 'utf8')
  const at = base.indexOf('- id: agent-default-model\n')
  for (const name of agents) {
    const plugins = expectedPlugins(name)
    const ids = plugins.map(plugin => plugin.replace(/^dsh-plugin-/, ''))
    assert.deepEqual(ours(`app_${name}`), ['app-recovery', 'app-limits', ...ids], name)
    const patch = await readFile(join(PROFILES, `app_${name}`, 'cordis.patch.yml'), 'utf8')
    const inserts = plugins.map(plugin => `- insert:\n    - id: ${plugin.replace(/^dsh-plugin-/, '')}\n      name: ${plugin}\n`).join('')
    // Everything of the base, byte for byte, around the inserts (and the agent's model, if any).
    const { agent } = readAgent(join(AGENTS, name, 'agent.yml'))
    assert.ok(patch.endsWith(`${inserts}${withModel(base.slice(at), name, agent.model)}`), name)
    assert.ok(patch.includes(base.slice(0, at)), name)
    // And dsh composes the model the agent runs on: its own, or the base's.
    const base_ = defaultModel('app')
    assert.deepEqual(defaultModel(`app_${name}`),
      agent.model ? { ...base_, model: agent.model.name, reasoningEffort: agent.model.reasoning } : base_, name)
    const manifest = JSON.parse(await readFile(join(PROFILES, `app_${name}`, 'package.json'), 'utf8'))
    const baseManifest = JSON.parse(await readFile(join(PROFILES, 'app', 'package.json'), 'utf8'))
    assert.deepEqual(manifest, { ...baseManifest, name: `dsh-profile-app_${name}` })
  }
  // The agents the baselines cover, spelled out.
  assert.deepEqual(expectedPlugins('summarizer'), ['dsh-plugin-app-fs', 'dsh-plugin-app-summarizer'])
})

test('every agent declares itself in agent.yml, outside its workspace', () => {
  for (const name of agents) {
    const { agent, error } = readAgent(join(AGENTS, name, 'agent.yml'))
    assert.equal(error, undefined, name)
    assert.ok(agent.description, name)
    assert.ok(!existsSync(join(AGENTS, name, 'workspace', 'agent.yml')), name)
  }
  // An own plugin's ends_run, read where the build reads it (through the symlink).
  const manifest = JSON.parse(readFileSync(join(AGENTS, 'summarizer', 'plugins', 'dsh-plugin-app-summarizer', 'package.json'), 'utf8'))
  assert.deepEqual(manifest.harness, { ends_run: ['finalize_summary'] })
})

test('the image carries every agent\'s limits for the server, as agent.yml declares them', () => {
  const written = JSON.parse(readFileSync(AGENTS_JSON, 'utf8'))
  assert.deepEqual(Object.keys(written).sort(), agents)
  for (const name of agents) {
    const { agent } = readAgent(join(AGENTS, name, 'agent.yml'))
    assert.deepEqual(written[name], { limits: agent.limits }, name)
  }
})

test('the generator refuses what would boot an agent wrong', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'app-profiles-test-'))
  try {
    const LIMITS = 'limits:\n  max_run_seconds: null\n  max_tokens: null\n  max_attempts: 3\n'
    const OWN = 'tools:\n  own:\n    one_tool:\n      effects:\n        writes: w\n      repeat:\n        fails: f\n'
    const run = async (setup, extra = []) => {
      const root = join(dir, String(Math.random()).slice(2))
      await cp(join(PROFILES, 'app'), join(root, 'profiles', 'app'), { recursive: true })
      await mkdir(join(root, 'agents', 'one', 'workspace'), { recursive: true })
      await writeFile(join(root, 'agents', 'one', 'agent.yml'), `description: An agent.\n${LIMITS}`)
      await setup(root)
      const args = extra.map(arg => arg.replace('$ROOT', root))
      const result = spawnSync(process.execPath, [GENERATOR, ...args, join(root, 'agents'), join(root, 'profiles')], { encoding: 'utf8' })
      return Object.assign(result, { root })
    }
    const agentYml = (root, text) => writeFile(join(root, 'agents', 'one', 'agent.yml'), text)
    const ok = await run(async () => {})
    assert.equal(ok.status, 0, ok.stderr)
    assert.match(ok.stdout, /app_one\n/)
    const json = await run(async () => {}, ['--agents-json', '$ROOT/out/agents.json'])
    assert.equal(json.status, 0, json.stderr)
    assert.deepEqual(JSON.parse(readFileSync(join(json.root, 'out', 'agents.json'), 'utf8')),
      { one: { limits: { max_run_seconds: null, max_tokens: null, max_attempts: 3 } } })
    // Never over a leftover: a stale file must not stand in for this build's.
    const stale = await run(root => mkdir(join(root, 'out')).then(() => writeFile(join(root, 'out', 'agents.json'), '{}')),
      ['--agents-json', '$ROOT/out/agents.json'])
    assert.notEqual(stale.status, 0)
    assert.match(stale.stderr, /EEXIST/)
    const bare = await run(async () => {}, ['--agents-json'])
    assert.equal(bare.status, 2, bare.stderr)
    const refused = async (setup, pattern) => {
      const result = await run(setup)
      assert.equal(result.status, 1, `${pattern}: ${result.stdout}`)
      assert.match(result.stderr, pattern)
    }
    const HEAD = `description: An agent.\n${LIMITS}`
    await refused(root => agentYml(root, `${HEAD}tools:\n  shared: [raed]\n`), /unknown tools: raed/)
    await refused(root => agentYml(root, `${HEAD}tools:\n  shared: [edit]\n`), /edit need read/)
    await refused(root => rm(join(root, 'agents', 'one', 'agent.yml')), /agent\.yml: missing/)
    await refused(root => agentYml(root, `${HEAD}description: e\n`), /duplicated mapping key/)
    await refused(root => agentYml(root, `${HEAD}queue: fast\n`), /unknown key queue/)
    await refused(root => agentYml(root, HEAD.replace('max_attempts: 3', 'max_attempts: 0')), /max_attempts: a positive integer/)
    await refused(root => agentYml(root, HEAD.replace('max_tokens: null', 'max_tokens: lots')), /max_tokens: a positive integer/)
    await refused(root => agentYml(root, `${HEAD}${OWN}`), /no plugins of its own/)
    const plugin = async (root, manifest) => {
      await mkdir(join(root, 'agents', 'one', 'plugins', 'dsh-plugin-one'), { recursive: true })
      await writeFile(join(root, 'agents', 'one', 'plugins', 'dsh-plugin-one', 'package.json'), JSON.stringify(manifest))
    }
    await refused(root => plugin(root, { name: 'dsh-plugin-one' }), /tools\.own lists the tools its plugins register/)
    const owned = async (root, manifest) => {
      await agentYml(root, `${HEAD}${OWN}`)
      await plugin(root, manifest)
    }
    const withOwn = await run(root => owned(root, { name: 'dsh-plugin-one', harness: { ends_run: ['one_tool'] } }))
    assert.equal(withOwn.status, 0, withOwn.stderr)
    assert.match(withOwn.stdout, /app_one \(dsh-plugin-one\)\n/)
    // A model of its own: written into its profile's agent-default-model, nowhere else.
    const MODEL = 'model:\n  name: deepseek-v4-pro\n  reasoning: high\n'
    const modeled = await run(root => agentYml(root, `${HEAD}${MODEL}`))
    assert.equal(modeled.status, 0, modeled.stderr)
    assert.match(modeled.stdout, /app_one \[deepseek-v4-pro\/high\]\n/)
    const modeledPatch = readFileSync(join(modeled.root, 'profiles', 'app_one', 'cordis.patch.yml'), 'utf8')
    assert.match(modeledPatch, /\n- id: agent-default-model\n {2}config:\n {4}provider: deepseek-official\n {4}model: deepseek-v4-pro {2}# agents\/one\/agent\.yml\n {4}reasoningEffort: high {2}# agents\/one\/agent\.yml\n?$/)
    assert.equal(readFileSync(join(modeled.root, 'profiles', 'app', 'cordis.patch.yml'), 'utf8'),
      readFileSync(join(PROFILES, 'app', 'cordis.patch.yml'), 'utf8'))
    await refused(root => agentYml(root, `${HEAD}model:\n  name: deepseek-v4-pro\n`), /model\.reasoning: one of off, low, high, max/)
    await refused(root => agentYml(root, `${HEAD}model:\n  name: Big Model 3\n  reasoning: low\n`), /model\.name: a model id/)
    await refused(root => agentYml(root, `${HEAD}${MODEL}  provider: deepseek\n`), /model: unknown key provider/)
    await refused(root => agentYml(root, `${HEAD}model: deepseek-v4-pro\n`), /model: a mapping with name and reasoning/)
    await refused(async root => {
      await agentYml(root, `${HEAD}${MODEL}`)
      const patch = join(root, 'profiles', 'app', 'cordis.patch.yml')
      await writeFile(patch, (await readFile(patch, 'utf8')).replace(/^ {4}reasoningEffort: .*\n?/m, ''))
    }, /one "    model:" and one "    reasoningEffort:" line/)
    await refused(root => owned(root, { name: 'dsh-plugin-one', harness: { ends_run: ['other_tool'] } }), /ends_run names other_tool/)
    await refused(root => owned(root, { name: 'dsh-plugin-one', harness: { ends_run: 'one_tool' } }), /non-empty list/)
    await refused(root => owned(root, { name: 'dsh-plugin-one', harness: { summary: 's' } }), /unknown harness key summary/)
    await refused(root => owned(root, { name: 'dsh-plugin-other' }), /is not the folder name/)
    await refused(root => owned(root, { name: 'dsh-plugin-one', harness: { tools: ['x'] } }), /declares no harness.tools/)
    const noAnchor = await run(async root => {
      const patch = join(root, 'profiles', 'app', 'cordis.patch.yml')
      await writeFile(patch, (await readFile(patch, 'utf8')).replace('- id: agent-default-model\n', '- id: agent-default-modelx\n'))
    })
    assert.equal(noAnchor.status, 1)
    assert.match(noAnchor.stderr, /exactly one top-level/)
  } finally {
    await rm(dir, { recursive: true, force: true })
  }
})
