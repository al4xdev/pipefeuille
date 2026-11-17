/**
 * Opt-in file tools confined to the process workspace: read, write, edit,
 * list, trash, apply_patch (+ apply_patch_undo). An agent lists the ones it
 * gets in the tools.shared of agents/<name>/agent.yml; the image build inserts this plugin only into
 * the profiles of those agents (app_<name>), and app-agent passes the list as
 * APP_TOOLS, checked again here. One dsh process runs one agent, so
 * registering at apply() is per agent. The names are declared in
 * package.json (`harness.tools`), the one list dsh-plugin-app-tools reads.
 *
 * Every path goes through workspace.js; see there for the rules.
 *
 * @module dsh-plugin-app-fs
 */

import { defineTool } from '@deepseek-ai/dsh-tools'
import { selectTools, toolsOf } from 'dsh-plugin-app-tools'
import * as files from './files.js'
import { applyPatch, undoPatch } from './patch.js'
import { guidance } from './tools.js'
import { openWorkspace } from './workspace.js'

export const name = 'app-fs'
export const inject = ['tools', 'systemPrompt']

const text = { schema: { type: 'string' }, render: (_args, value) => [{ type: 'text', text: value }] }
const FS = toolsOf('dsh-plugin-app-fs')

export function apply(ctx) {
  const selected = selectTools(process.env.APP_TOOLS)
  if (selected.error) console.error(JSON.stringify({ severity: 'ERROR', component: 'app-fs', event: 'bad_tools', error: selected.error }))
  const tools = new Set([...selected.tools].filter(tool => FS.includes(tool)))
  if (!tools.size) return

  // Per session cwd (one per process): the workspace, what was read, and patch receipts.
  const states = new Map()
  const stateOf = exec => {
    const cwd = exec.agent?.session.header.cwd
    if (!states.has(cwd)) {
      states.set(cwd, openWorkspace(cwd).then(ws => ({ ws, obs: new files.Observations(), receipts: new Map() })))
      // A failed open is not cached: the next call reports it again.
      states.get(cwd).catch(() => states.delete(cwd))
    }
    return states.get(cwd)
  }
  const run = fn => async (args, exec) => {
    exec.signal?.throwIfAborted()
    let state
    try {
      state = await stateOf(exec)
      return await fn(state, args)
    } catch (error) {
      // Without a workspace the only error is openWorkspace's own refusal.
      if (!state || !(error instanceof Error)) throw error
      const message = state.ws.scrub(error)
      if (message === error.message) throw error
      throw Object.assign(new Error(message), { code: error.code ?? error.cause?.code })
    }
  }

  const prompt = guidance(tools)
  ctx.systemPrompt.section({
    name: 'tool:app-fs',
    order: ctx.systemPrompt.getSectionOrder('TOOL_READ'),
    text: () => prompt,
  })

  const path = description => ({ type: 'string', required: true, description })
  const register = (tool, definition) => tools.has(tool) && ctx.tools.register(defineTool({ output: text, ...definition }))

  register('read', {
    name: 'read',
    description: 'Read a UTF-8 text file from your workspace and return line-numbered content.',
    parameters: {
      file_path: path('File path, relative to your workspace.'),
      offset: { type: 'number', description: '1-based first line to return. Defaults to 1.' },
      limit: { type: 'number', description: `Maximum number of lines to return. Defaults to ${files.READ_LIMIT}.` },
    },
    isConcurrencySafe: () => true,
    execute: run(({ ws, obs }, args) => files.read(ws, obs, args)),
  })
  register('write', {
    name: 'write',
    description: 'Create or fully replace a UTF-8 text file in your workspace. Missing folders are created.',
    parameters: {
      file_path: path('File path, relative to your workspace.'),
      content: { type: 'string', required: true, description: 'Full UTF-8 text content to write.' },
    },
    execute: run(({ ws, obs }, args) => files.write(ws, obs, args)),
  })
  register('edit', {
    name: 'edit',
    description: 'Edit a file in your workspace by replacing literal text.',
    parameters: {
      file_path: path('File path, relative to your workspace.'),
      old_string: { type: 'string', required: true, description: 'Literal text to replace; must match once unless replace_all.' },
      new_string: { type: 'string', required: true, description: 'Literal replacement text. An empty string deletes the match.' },
      replace_all: { type: 'boolean', description: 'Replace every match. Defaults to false.' },
    },
    execute: run(({ ws, obs }, args) => files.edit(ws, obs, args)),
  })
  register('list', {
    name: 'list',
    description: 'List entries of a folder in your workspace. Folders end with "/" and come before files.',
    parameters: {
      path: { type: 'string', description: 'Folder, relative to your workspace. Defaults to the workspace itself.' },
      depth: { type: 'number', description: 'How many levels to descend. Defaults to 1.' },
      limit: { type: 'number', description: 'Maximum number of entries. Defaults to 200.' },
      hidden: { type: 'boolean', description: 'Include entries starting with ".". Defaults to true.' },
    },
    isConcurrencySafe: () => true,
    execute: run(({ ws }, args) => files.list(ws, args)),
  })
  register('trash', {
    name: 'trash',
    description: 'Recoverably remove files or folders from your workspace: each is moved into .dumps/.trash/. Not atomic: each path reports its own result.',
    parameters: {
      paths: { type: 'array', items: { type: 'string' }, required: true, description: 'Explicit paths, relative to your workspace (no globs).' },
    },
    execute: run(({ ws, obs }, args) => files.trash(ws, obs, args)),
  })
  if (tools.has('apply_patch')) {
    register('apply_patch', {
      name: 'apply_patch',
      description: 'Apply a Codex-format patch to files in your workspace. Exact context only. Checked before writing but NOT atomic across files. Returns a receipt with each file\'s state (changed/unchanged/partial/uncertain).',
      parameters: {
        patch: path('Read the changed lines first; read entire files before moving or deleting them. Example: *** Begin Patch\n*** Update File: notes.md\n@@\n-old text\n+new text\n*** End Patch\n\nEach line starts with one marker (space, -, +); everything after it is literal. Operations: Add File, Delete File, Update File (optionally followed by *** Move to: path).'),
      },
      execute: run(({ ws, obs, receipts }, args) => applyPatch(ws, obs, receipts, args.patch)),
    })
    ctx.tools.register(defineTool({
      name: 'apply_patch_undo',
      description: 'Undo a patch from this run by its receipt, without overwriting changes made after it. May partly succeed; returns each file\'s undo state.',
      parameters: { manifest: path('The manifest path in the apply_patch receipt.') },
      output: text,
      execute: run(({ ws, obs, receipts }, args) => undoPatch(ws, obs, receipts, args.manifest)),
    }))
  }
}