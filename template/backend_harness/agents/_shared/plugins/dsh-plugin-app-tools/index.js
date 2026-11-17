/**
 * Which opt-in tools an agent gets: the names, and the checks of a list of them
 * (the `tools.shared` of agents/<name>/agent.yml, read by ./agent.js) and of
 * APP_TOOLS. app-agent (through cli.js), the profile generator
 * (runtime/bin/app-profiles.mjs), context.mjs and every opt-in plugin use this
 * module, so a tool name is known and checked in exactly one place. It imports
 * nothing beyond node: the opt-in plugins load it at every boot.
 *
 * The names are not kept here: each shared plugin declares the tools it
 * registers in its own package.json (`"harness": {"tools": [...]}`), and this module
 * reads them from its sibling packages (agents/_shared/plugins in the repo,
 * /opt/dsh/node_modules in the image). A bad declaration (a duplicate or
 * malformed name) throws at import, so every user fails loudly, the image build
 * included.
 *
 * A library, not a plugin: no `apply`, no profile entry.
 *
 * @module dsh-plugin-app-tools
 */

import { readdirSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

// The folder holding this package and its siblings (import.meta.url is the real
// path: node resolves the profile's symlinks).
const PACKAGES = join(dirname(fileURLToPath(import.meta.url)), '..')
// Only our plugins can declare tools; skipping the rest keeps the scan of
// /opt/dsh/node_modules (dsh's own dependencies) to a few package.json reads.
const PREFIX = 'dsh-plugin-'
const NAME = /^[a-z][a-z0-9_]*$/

function readDeclarations() {
  const plugins = new Map()
  const owner = new Map()
  for (const entry of readdirSync(PACKAGES).filter(name => name.startsWith(PREFIX)).sort()) {
    let manifest
    try {
      manifest = JSON.parse(readFileSync(join(PACKAGES, entry, 'package.json'), 'utf8'))
    } catch {
      continue
    }
    const tools = manifest.harness?.tools
    if (tools === undefined) continue
    if (!Array.isArray(tools) || tools.length === 0) throw new Error(`dsh-plugin-app-tools: ${entry}: harness.tools must be a non-empty list`)
    for (const tool of tools) {
      if (typeof tool !== 'string' || !NAME.test(tool)) throw new Error(`dsh-plugin-app-tools: ${entry}: bad tool name ${JSON.stringify(tool)}`)
      if (owner.has(tool)) throw new Error(`dsh-plugin-app-tools: tool ${tool} declared by both ${owner.get(tool)} and ${entry}`)
      owner.set(tool, entry)
    }
    plugins.set(entry, [...tools])
  }
  return { plugins, owner }
}

const { plugins: PLUGINS, owner: OWNER } = readDeclarations()

/** Every opt-in tool name, plugin by plugin (package name order), each in its declared order. */
export const KNOWN = [...PLUGINS.values()].flat()
// Both change a file in place from what the model saw: without read they can only fail.
const NEEDS_READ = ['edit', 'apply_patch']

/** The tools a shared plugin declares (empty for any other package). */
export function toolsOf(plugin) {
  return [...(PLUGINS.get(plugin) ?? [])]
}

/** The shared plugin that registers a known tool (undefined for an unknown one). */
export function pluginOf(tool) {
  return OWNER.get(tool)
}

/** A list of names checked: the selected set, or an error message (and no tools). */
export function checkTools(names) {
  const unknown = names.filter(name => !KNOWN.includes(name))
  if (unknown.length) return { tools: new Set(), error: `unknown tools: ${unknown.join(', ')}` }
  const tools = new Set(names)
  const orphan = NEEDS_READ.filter(name => tools.has(name) && !tools.has('read'))
  if (orphan.length) return { tools: new Set(), error: `${orphan.join(', ')} need read` }
  return { tools }
}

/** APP_TOOLS (comma-separated, as app-agent exports it), failing closed. */
export function selectTools(value) {
  const { tools, error } = checkTools((value ?? '').split(',').map(name => name.trim()).filter(Boolean))
  return error ? { tools, error: `${error} in APP_TOOLS` } : { tools }
}
