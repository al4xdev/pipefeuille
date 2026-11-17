/**
 * read, write, edit, list and trash, on the fence in workspace.js.
 *
 * Copied, then changed to go through the fence and show workspace-relative paths:
 * - read window and envelope: @deepseek-ai/dsh-tool-fs (DSH_VERSION 0.2.0-rc.2),
 *   lib/index.js buildWindow / formatReadOutput / parseReadArgs;
 * - list: dsh-customs plugins/list/index.mjs (collectEntries, formatListOutput);
 * - read-before-change coverage: dsh-customs plugins/apply-patch/observation.mjs.
 *
 * @module dsh-plugin-app-fs/files
 */

import { randomBytes } from 'node:crypto'
import { lstat, mkdir, readdir, readFile, realpath, rename, stat } from 'node:fs/promises'
import { basename, join, relative } from 'node:path'
import { FenceError, MAX_FILE_BYTES, TRASH, atomicWrite, under, versionOf } from './workspace.js'

export const READ_LIMIT = 2000
const READ_MAX_LINE_LENGTH = 2000
const READ_MAX_BYTES = 50 * 1024
const TRUNCATED = '... (line truncated to '
/** What this process read or wrote, per absolute path: the version, and which lines. */
export class Observations {
  #entries = new Map()

  // A line cut at 2000 chars counts as read: no read shows more of it, and edit
  // and apply_patch match exact text, so its unseen tail cannot be changed blindly.
  read(abs, version, lines, totalLines) {
    let entry = this.#entries.get(abs)
    if (!entry || entry.version !== version) entry = { version, full: false, lines: new Set() }
    for (const line of lines) entry.lines.add(line.number)
    entry.full ||= entry.lines.size === totalLines
    this.#entries.set(abs, entry)
  }

  wrote(abs, version) {
    this.#entries.set(abs, { version, full: true, lines: new Set() })
  }

  /** Forget a path and everything under it (it was moved away). */
  forget(abs) {
    for (const key of this.#entries.keys()) if (under(key, abs)) this.#entries.delete(key)
  }

  /**
   * The entry for a change at `version`, or a refusal telling the model to read.
   * @param lines - 0-based line indices the change touches; full = the whole file.
   */
  require(abs, version, shown, { full = false, lines = [] } = {}) {
    const entry = this.#entries.get(abs)
    if (!entry) throw new FenceError(`cannot change "${shown}": it has not been read; read it, then retry`, 'APP_FS_NOT_OBSERVED')
    if (entry.version !== version) throw new FenceError(`"${shown}" changed since it was read; read it again, then retry`, 'APP_FS_STALE')
    if (!entry.full && (full || lines.some(i => !entry.lines.has(i + 1)))) {
      throw new FenceError(`read ${full ? 'the entire file' : 'the changed lines and their context'} of "${shown}" first`, 'APP_FS_NOT_OBSERVED')
    }
    return entry
  }
}

function positiveInteger(value, name) {
  if (!Number.isFinite(value) || !Number.isInteger(value) || value < 1) throw new Error(`${name} must be a positive integer`)
  return value
}

/** UTF-8 text of a regular file, or a refusal; `shown` is the model-facing path. */
export async function readTextFile(real, shown) {
  const st = await stat(real, { bigint: true })
  if (st.isDirectory()) throw new FenceError(`"${shown}" is a directory; use list`, 'APP_FS_IS_DIRECTORY')
  if (!st.isFile()) throw new FenceError(`"${shown}": not found`, 'APP_FS_NOT_FOUND')
  if (st.size > BigInt(MAX_FILE_BYTES)) throw new FenceError(`"${shown}" is larger than ${MAX_FILE_BYTES / 1024 / 1024} MiB`, 'APP_FS_TOO_LARGE')
  const bytes = await readFile(real)
  let text
  try {
    if (bytes.subarray(0, 8192).includes(0)) throw new Error('binary')
    text = new TextDecoder('utf-8', { fatal: true }).decode(bytes)
  } catch {
    throw new FenceError(`"${shown}" is not a UTF-8 text file`, 'APP_FS_BINARY')
  }
  return { text, version: versionOf(st) }
}

function buildWindow(text, request) {
  const lines = []
  let totalLines = 0
  let outputBytes = 0
  let truncatedByBytes = false
  const all = text.split('\n')
  if (all.at(-1) === '') all.pop()
  for (const raw of all) {
    totalLines += 1
    if (truncatedByBytes || totalLines < request.offset || lines.length >= request.limit) continue
    const line = raw.endsWith('\r') ? raw.slice(0, -1) : raw
    const shown = line.length > READ_MAX_LINE_LENGTH ? `${line.substring(0, READ_MAX_LINE_LENGTH)}${TRUNCATED}${READ_MAX_LINE_LENGTH} chars)` : line
    const bytes = Buffer.byteLength(shown) + (lines.length > 0 ? 1 : 0)
    if (outputBytes + bytes > READ_MAX_BYTES) {
      truncatedByBytes = true
      continue
    }
    outputBytes += bytes
    lines.push({ number: totalLines, text: shown })
  }
  return { lines, totalLines, truncatedByBytes }
}

function formatReadOutput(path, outcome) {
  const endLine = outcome.lines.at(-1)?.number ?? Math.max(0, outcome.offset - 1)
  let footer
  if (outcome.truncatedByBytes) footer = `(Output capped. Showing lines ${outcome.offset}-${endLine}. Use offset=${endLine + 1} to continue.)`
  else if (endLine < outcome.totalLines) footer = `(Showing lines ${outcome.offset}-${endLine} of ${outcome.totalLines}. Use offset=${endLine + 1} to continue.)`
  else footer = `(End of file - total ${outcome.totalLines} lines)`
  const body = outcome.lines.length > 0 ? `${outcome.lines.map(line => `${line.number}: ${line.text}`).join('\n')}\n\n${footer}` : footer
  return `<path>${path}</path>\n<type>file</type>\n<content>\n${body}\n</content>`
}

export async function read(ws, obs, args) {
  const offset = args.offset === undefined ? 1 : positiveInteger(args.offset, 'offset')
  const limit = args.limit === undefined ? READ_LIMIT : positiveInteger(args.limit, 'limit')
  if (limit > READ_LIMIT) throw new Error(`limit must be less than or equal to ${READ_LIMIT}`)
  const { abs, rel, real } = await ws.resolveRead(args.file_path)
  const { text, version } = await readTextFile(real, rel)
  const window = buildWindow(text, { offset, limit })
  if (offset > window.totalLines && !(window.totalLines === 0 && offset === 1)) {
    throw new FenceError(`offset ${offset} is out of range for "${rel}" (${window.totalLines} lines)`, 'APP_FS_NOT_FOUND')
  }
  obs.read(abs, version, window.lines, window.totalLines)
  return formatReadOutput(rel, { offset, ...window })
}

export function contentBytes(content) {
  if (typeof content !== 'string') throw new Error('content must be a string')
  const bytes = Buffer.byteLength(content)
  if (bytes > MAX_FILE_BYTES) throw new FenceError(`a file can hold at most ${MAX_FILE_BYTES / 1024 / 1024} MiB`, 'APP_FS_TOO_LARGE')
  return bytes
}

const confirmation = (path, word) => `<path>${path}</path>\n<type>file</type>\n<content>\n${word} file\n</content>`

export async function write(ws, obs, args) {
  const bytes = contentBytes(args.content)
  const target = await ws.resolveMutation(args.file_path)
  if (target.leaf?.isDirectory()) throw new FenceError(`"${target.rel}" is a directory`, 'APP_FS_IS_DIRECTORY')
  // Overwriting replaces every line: it needs the whole file read at its current version.
  if (target.leaf) obs.require(target.abs, versionOf(target.leaf), target.rel, { full: true })
  await ws.assertFits(bytes - (target.leaf ? Number(target.leaf.size) : 0), target.missing)
  await ws.ensureParent(target.abs)
  await atomicWrite(target.abs, args.content)
  obs.wrote(target.abs, await ws.stamp(target.abs))
  return confirmation(target.rel, target.leaf ? 'Updated' : 'Created')
}

export async function edit(ws, obs, args) {
  const { old_string: oldString, new_string: newString, replace_all: replaceAll = false } = args
  if (typeof oldString !== 'string' || oldString === '') throw new Error('old_string must be a non-empty string')
  if (typeof newString !== 'string') throw new Error('new_string must be a string')
  if (oldString === newString) throw new Error('old_string and new_string are identical')
  const target = await ws.resolveMutation(args.file_path)
  if (!target.leaf) throw new FenceError(`"${target.rel}": not found`, 'APP_FS_NOT_FOUND')
  if (!target.leaf.isFile()) throw new FenceError(`"${target.rel}" is not a file`, 'APP_FS_NOT_FOUND')
  const version = versionOf(target.leaf)
  obs.require(target.abs, version, target.rel)
  const { text: before, version: readVersion } = await readTextFile(target.abs, target.rel)
  if (readVersion !== version) throw new FenceError(`"${target.rel}" changed since it was read; read it again, then retry`, 'APP_FS_STALE')
  const count = before.split(oldString).length - 1
  if (count === 0) throw new FenceError(`old_string not found in "${target.rel}"; read it again`, 'APP_FS_NO_MATCH')
  if (count > 1 && !replaceAll) {
    throw new FenceError(`old_string appears ${count} times in "${target.rel}"; add context to make it unique, or set replace_all`, 'APP_FS_AMBIGUOUS_EDIT')
  }
  // Every line a replaced match spans must have been read.
  const span = oldString.split('\n').length
  const touched = []
  for (let at = before.indexOf(oldString); at !== -1; at = replaceAll ? before.indexOf(oldString, at + oldString.length) : -1) {
    const first = before.slice(0, at).split('\n').length - 1
    for (let i = 0; i < span; i++) touched.push(first + i)
  }
  obs.require(target.abs, version, target.rel, { lines: touched })
  // split/join and slices, never String.replace: "$&" in new_string must stay literal.
  const at = before.indexOf(oldString)
  const after = replaceAll ? before.split(oldString).join(newString) : before.slice(0, at) + newString + before.slice(at + oldString.length)
  const bytes = contentBytes(after)
  await ws.assertFits(bytes - Number(target.leaf.size), 0)
  await atomicWrite(target.abs, after)
  obs.wrote(target.abs, await ws.stamp(target.abs))
  return confirmation(target.rel, 'Updated')
}

const LIST_DEFAULT = 200
const LIST_MAX = 1000
const LIST_MAX_DEPTH = 8
const LIST_MAX_BYTES = 64 * 1024
const typeRank = type => (type === 'directory' ? 0 : type === 'file' ? 1 : 2)

export async function list(ws, args) {
  const depth = args.depth === undefined ? 1 : positiveInteger(args.depth, 'depth')
  if (depth > LIST_MAX_DEPTH) throw new Error(`depth must be less than or equal to ${LIST_MAX_DEPTH}`)
  const limit = args.limit === undefined ? LIST_DEFAULT : positiveInteger(args.limit, 'limit')
  if (limit > LIST_MAX) throw new Error(`limit must be less than or equal to ${LIST_MAX}`)
  const hidden = args.hidden !== false
  const { rel, real } = await ws.resolveRead(args.path ?? '.')
  if (!(await stat(real)).isDirectory()) throw new FenceError(`"${rel}" is not a directory`, 'APP_FS_NOT_DIRECTORY')

  const entries = []
  const visited = new Set([real])
  let total = 0
  let bytes = 0
  let truncated = false
  const visit = async (dir, prefix, level) => {
    const children = []
    for (const entry of await readdir(dir, { withFileTypes: true })) {
      if (!hidden && entry.name.startsWith('.')) continue
      let type = entry.isDirectory() ? 'directory' : entry.isFile() ? 'file' : 'other'
      let into = entry.isDirectory() ? join(dir, entry.name) : undefined
      if (entry.isSymbolicLink()) {
        // A link is entered only when its target is readable; otherwise it is listed, not followed.
        try {
          const target = await realpath(join(dir, entry.name))
          if (ws.readable(target)) {
            const st = await stat(target)
            type = st.isDirectory() ? 'directory' : st.isFile() ? 'file' : 'other'
            into = st.isDirectory() ? target : undefined
          }
        } catch {
          // dangling link: listed as other
        }
      }
      children.push({ name: entry.name, type, into })
    }
    children.sort((a, b) => typeRank(a.type) - typeRank(b.type) || a.name.localeCompare(b.name))
    for (const child of children) {
      const path = prefix ? join(prefix, child.name) : child.name
      total += 1
      if (!truncated) {
        const entryBytes = Buffer.byteLength(path) + 1
        if (entries.length >= limit || bytes + entryBytes > LIST_MAX_BYTES) truncated = true
        else {
          entries.push({ type: child.type, path })
          bytes += entryBytes
        }
      }
      if (child.into && level < depth && !visited.has(child.into)) {
        visited.add(child.into)
        await visit(child.into, path, level + 1)
      }
    }
  }
  await visit(real, '', 1)

  const lines = entries.map(entry => (entry.type === 'directory' ? `${entry.path}/` : entry.path))
  let footer
  if (total === 0) footer = 'Empty directory'
  else if (truncated) footer = `Showing ${entries.length} of ${total} entries (capped); narrow depth or limit to see more.`
  else footer = `${total} ${total === 1 ? 'entry' : 'entries'}`
  if (!hidden) footer += '; hidden entries omitted'
  const body = lines.length ? `${lines.join('\n')}\n\n${footer}` : footer
  return `<path>${rel}</path>\n<type>directory</type>\n<content>\n${body}\n</content>`
}

// Trash names get a 32-byte prefix: keep the whole name under NAME_MAX (255).
function shortName(name, maxBytes = 200) {
  let out = ''
  for (const char of name) {
    if (Buffer.byteLength(out + char) > maxBytes) break
    out += char
  }
  return out
}

/**
 * Move one path into .dumps/.trash/ (inside the workspace, so it still counts
 * against the quota and is still readable). A link is moved as a link. The
 * fence refuses .dumps, .dumps/.trash and .dumps/.patch themselves.
 * @returns the model-facing recovery path.
 */
export async function trashOne(ws, obs, path) {
  const target = await ws.resolveMutation(path, { linkLeaf: true })
  if (!target.leaf) throw new FenceError(`"${target.rel}": not found`, 'APP_FS_NOT_FOUND')
  const trashDir = join(ws.root, TRASH)
  // The trash folder goes through the same no-link rule as any other change.
  await ws.resolveMutation(join(TRASH, 'entry'), { internal: true })
  await mkdir(trashDir, { recursive: true })
  const stampText = new Date().toISOString().replace(/[:.]/g, '-')
  const destination = join(trashDir, `${stampText}-${randomBytes(3).toString('hex')}-${shortName(basename(target.abs))}`)
  const free = await lstat(destination).then(() => false, error => {
    if (error.code === 'ENOENT') return true
    throw error
  })
  if (!free) throw new FenceError('trash name collision; retry', 'APP_FS_CONFLICT')
  await rename(target.abs, destination)
  obs.forget(target.abs)
  return relative(ws.root, destination)
}

export async function trash(ws, obs, args) {
  const { paths } = args
  if (!Array.isArray(paths) || paths.length === 0 || paths.length > 100) throw new Error('paths must be a list of 1 to 100 paths')
  const results = []
  for (const path of paths) {
    try {
      results.push({ path, status: 'moved', recovery: await trashOne(ws, obs, path) })
    } catch (error) {
      results.push({ path, status: 'not_moved', error: ws.scrub(error) })
    }
  }
  return JSON.stringify({ atomic: false, results })
}