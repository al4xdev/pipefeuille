#!/usr/bin/env node
// Image build step: one dsh profile per agent, `app_<name>`, derived from the
// base `app` profile. dsh has no per-agent plugins, so loading is the harness's
// job: an agent's profile is `app` plus one `insert` per plugin it gets,
//   - the shared plugins that register the tools the `tools.shared` of its
//     agents/<name>/agent.yml lists (each tool's plugin comes from
//     dsh-plugin-app-tools, i.e. the plugins' own package.json), in package
//     name order;
//   - every folder of agents/<name>/plugins (its own), in name order;
// placed right before the base patch's `agent-default-model` entry, where the
// runtime's own inserts end. An agent with neither gets a copy of `app`.
// An agent.yml `model` (name, reasoning) replaces the `model:` and
// `reasoningEffort:` lines of that entry in the agent's profile only; the
// provider stays the base's. Without it the agent runs on the base's default.
// A missing or bad agent.yml (bad YAML, a duplicate or unknown key, an unknown
// tool) or plugin folder fails the build: an agent must never boot without the
// plugins it declares, or with someone else's. An own plugin may say in its
// package.json which of its tools end the run (`"harness": {"ends_run": [...]}`);
// those must be `tools.own` entries. Which tools an own plugin registers only
// the context capture shows (tests/context.sh); the logic side's gates may hold
// `tools.own` to it.
//
// With --agents-json <file> it also writes every agent's limits there, as
// {"<name>": {"limits": {...}}}: what the harness server reads at startup
// (server/server.py AGENTS_FILE), so agent.yml keeps one parser, this one's.
//
//   node app-profiles.mjs [--agents-json <file>] <agents dir> <profiles dir> [<dsh-plugin-app-tools index.js>]
import { cpSync, existsSync, mkdirSync, readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { pathToFileURL } from 'node:url'

const argv = process.argv.slice(2)
let agentsJson
if (argv[0] === '--agents-json') {
  agentsJson = argv[1] ?? ''
  argv.splice(0, 2)
}
const [agentsDir, profilesDir, toolsModule = '/opt/dsh/node_modules/dsh-plugin-app-tools/index.js'] = argv
if (!agentsDir || !profilesDir || argv.length > 3 || (agentsJson !== undefined && !agentsJson)) {
  process.stderr.write('usage: app-profiles.mjs [--agents-json <file>] <agents dir> <profiles dir> [<dsh-plugin-app-tools index.js>]\n')
  process.exit(2)
}
const { pluginOf } = await import(pathToFileURL(toolsModule).href)
const { readAgent } = await import(pathToFileURL(join(dirname(toolsModule), 'agent.js')).href)

const BASE = 'app'
// The patch entry the agent inserts go before (the runtime's inserts end there).
const ANCHOR = '- id: agent-default-model\n'
// app-agent's rule for an agent name (letters, digits, '_', not leading '_').
const AGENT_NAME = /^[A-Za-z0-9][A-Za-z0-9_]*$/
const PLUGIN_PREFIX = 'dsh-plugin-'
// The keys an own plugin's package.json may hold under `harness`.
const OWN_KEYS = ['ends_run']

const fail = message => {
  process.stderr.write(`app-profiles: ${message}\n`)
  process.exit(1)
}

const baseDir = join(profilesDir, BASE)
const basePatch = readFileSync(join(baseDir, 'cordis.patch.yml'), 'utf8')
const anchorAt = basePatch.indexOf(ANCHOR)
if (anchorAt < 0 || anchorAt !== basePatch.lastIndexOf(ANCHOR) || (anchorAt > 0 && basePatch[anchorAt - 1] !== '\n')) {
  fail(`${baseDir}/cordis.patch.yml must hold exactly one top-level "${ANCHOR.trim()}" line`)
}
const baseManifest = JSON.parse(readFileSync(join(baseDir, 'package.json'), 'utf8'))
// The anchor entry is the base patch's last, so its lines are everything after
// the anchor; an agent's model replaces exactly one of each.
const MODEL_LINE = /^ {4}model: .*$/gm
const EFFORT_LINE = /^ {4}reasoningEffort: .*$/gm
const baseTail = basePatch.slice(anchorAt)

function tailFor(name, model) {
  if (model === null) return baseTail
  if ((baseTail.match(MODEL_LINE) ?? []).length !== 1 || (baseTail.match(EFFORT_LINE) ?? []).length !== 1) {
    fail(`${baseDir}/cordis.patch.yml: agent-default-model must end the file with one "    model:" and one "    reasoningEffort:" line (agents/${name}/agent.yml sets a model)`)
  }
  return baseTail
    .replace(MODEL_LINE, `    model: ${model.name}  # agents/${name}/agent.yml`)
    .replace(EFFORT_LINE, `    reasoningEffort: ${model.reasoning}  # agents/${name}/agent.yml`)
}

// One insert per plugin; the entry id is the package name without the prefix
// (dsh-plugin-app-fs is app-fs), as the base profile names its own.
const insert = plugin => `- insert:\n    - id: ${plugin.slice(PLUGIN_PREFIX.length)}\n      name: ${plugin}\n`

function ownPlugins(name, agent) {
  const dir = join(agentsDir, name, 'plugins')
  const plugins = existsSync(dir) ? readdirSync(dir).sort() : []
  const own = new Set(agent.own)
  const where = join(agentsDir, name, 'agent.yml')
  const result = plugins.map(plugin => {
    const path = join(dir, plugin)
    // statSync follows the symlink the build leaves to the installed copy.
    if (!statSync(path).isDirectory()) fail(`${path} is not a folder`)
    if (!plugin.startsWith(PLUGIN_PREFIX)) fail(`${path}: a plugin folder is named ${PLUGIN_PREFIX}*`)
    const manifest = JSON.parse(readFileSync(join(path, 'package.json'), 'utf8'))
    // dsh resolves the insert by package name, and the build installs it under the folder name.
    if (manifest.name !== plugin) fail(`${path}: package.json name ${JSON.stringify(manifest.name)} is not the folder name`)
    // Tool declarations are for shared plugins, which agents opt into by name.
    if (manifest.harness?.tools !== undefined) fail(`${path}: an agent's own plugin declares no harness.tools`)
    const extra = Object.keys(manifest.harness ?? {}).filter(key => !OWN_KEYS.includes(key))
    if (extra.length) fail(`${path}: unknown harness key ${extra.join(', ')} in package.json (only ${OWN_KEYS.join(', ')})`)
    const ends = manifest.harness?.ends_run
    if (ends !== undefined) {
      if (!Array.isArray(ends) || ends.length === 0 || !ends.every(tool => typeof tool === 'string')) {
        fail(`${path}: harness.ends_run is a non-empty list of tool names`)
      }
      const undeclared = ends.filter(tool => !own.has(tool))
      if (undeclared.length) fail(`${path}: harness.ends_run names ${undeclared.join(', ')}, which tools.own of ${where} does not`)
    }
    return plugin
  })
  // Own entries without own plugins describe tools nobody registers; own
  // plugins without entries register tools nothing describes.
  if (plugins.length && !own.size) fail(`${where}: agents/${name}/plugins exists, so tools.own lists the tools its plugins register`)
  if (!plugins.length && own.size) fail(`${where}: tools.own lists ${[...own].join(', ')}, but the agent has no plugins of its own`)
  return result
}

function sharedPlugins(agent) {
  return [...new Set([...agent.shared].map(pluginOf))].sort()
}

const made = []
const limits = {}
for (const name of readdirSync(agentsDir).sort()) {
  if (!existsSync(join(agentsDir, name, 'workspace'))) continue
  if (!AGENT_NAME.test(name)) fail(`invalid agent name: ${name}`)
  const { agent, error } = readAgent(join(agentsDir, name, 'agent.yml'))
  if (error) fail(error)
  limits[name] = { limits: agent.limits }
  const plugins = [...sharedPlugins(agent), ...ownPlugins(name, agent)]
  const profile = `${BASE}_${name}`
  const dir = join(profilesDir, profile)
  if (existsSync(dir)) fail(`${dir} already exists`)
  mkdirSync(dir)
  writeFileSync(join(dir, 'package.json'), `${JSON.stringify({ ...baseManifest, name: `dsh-profile-${profile}` }, null, 2)}\n`)
  cpSync(join(baseDir, 'cordis.yml'), join(dir, 'cordis.yml'))
  const inserts = plugins.length
    ? `# agents/${name}: its plugins (generated by app-profiles.mjs at image build).\n${plugins.map(insert).join('')}`
    : ''
  writeFileSync(join(dir, 'cordis.patch.yml'), [
    `# GENERATED at image build by runtime/bin/app-profiles.mjs: the\n# ${BASE} profile plus agent ${name}'s plugins. Edit runtime/profiles/${BASE} or agents/${name}.\n`,
    basePatch.slice(0, anchorAt),
    inserts,
    tailFor(name, agent.model),
  ].join(''))
  made.push(`${profile}${plugins.length ? ` (${plugins.join(', ')})` : ''}${agent.model ? ` [${agent.model.name}/${agent.model.reasoning}]` : ''}`)
}
if (agentsJson !== undefined) {
  if (!made.length) fail(`${agentsDir}: no agents, so no ${agentsJson}`)
  // flag 'wx': a leftover file from another build must never stand in for this one.
  mkdirSync(dirname(agentsJson), { recursive: true })
  writeFileSync(agentsJson, `${JSON.stringify(limits, null, 2)}\n`, { flag: 'wx' })
}
process.stdout.write(`app-profiles: ${made.join('; ')}\n`)
