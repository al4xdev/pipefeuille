/**
 * The fence every app-fs tool goes through: one agent process sees and changes
 * only its workspace, /tmp/app-work/<tenant>/<agent_name>/<process_id>/, plus
 * read access to its own template (the workspace's AGENTS.md and .agents/ are
 * symlinks into /opt/app/agents/<agent_name>/workspace/).
 *
 * Why not ctx.fs: the mounted backend (dsh-fs-sandbox) confines writes only,
 * allows all of /tmp in workspace-write (every tenant's workspace is there),
 * follows symlinks and returns absolute paths, which carry the tenant id.
 *
 * Paths the model sees are relative to the workspace. A path outside it fails
 * exactly like a missing file, so the model cannot probe what exists outside.
 *
 * Race: checks and the syscalls after them are separate steps. Exploiting the
 * gap needs a second writer in the workspace; the only writer is the agent,
 * through these tools, with no shell. Revisit if agents ever get one.
 *
 * @module dsh-plugin-app-fs/workspace
 */

import { randomBytes } from 'node:crypto'
import { lstat, mkdir, readdir, realpath, rename, rm, writeFile } from 'node:fs/promises'
import { dirname, isAbsolute, join, normalize, relative, resolve, sep } from 'node:path'

export const WORK = '/tmp/app-work'
export const AGENTS = '/opt/app/agents'
export const MAX_PATH_BYTES = 4096
// Linux NAME_MAX: a longer segment fails in the kernel with an absolute path in the error.
export const MAX_NAME_BYTES = 255
// /tmp may be RAM (a tmpfs, many container platforms) and the server's slots
// assume ~192 MiB per agent: one agent filling it would take the others down.
export const MAX_FILE_BYTES = 16 * 1024 * 1024
export const MAX_WORKSPACE_BYTES = 64 * 1024 * 1024
export const MAX_WORKSPACE_ENTRIES = 10000
// Ours, inside the workspace: the model may read them, never change them directly.
export const DUMPS = '.dumps'
export const TRASH = join(DUMPS, '.trash')
export const PATCHES = join(DUMPS, '.patch')
const reserved = rel => rel === DUMPS || under(rel, TRASH) || under(rel, PATCHES)

const UUID = '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'

export class FenceError extends Error {
  constructor(message, code) {
    super(message)
    this.code = code
  }
}

const escapeRegExp = text => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
export const under = (path, base) => path === base || path.startsWith(base + sep)
const notFound = path => new FenceError(`"${path}": not found`, 'APP_FS_NOT_FOUND')
const readOnly = path => new FenceError(`cannot change "${path}": it is a read-only link`, 'APP_FS_READ_ONLY')

/**
 * The ids of this process, from the session cwd app-agent made. Fail closed:
 * any other cwd, or a tenant that differs from the server's APP_TENANT_ID,
 * leaves every tool refusing.
 */
export function processIds(cwd, { env = process.env, work = WORK } = {}) {
  const shape = new RegExp(`^${escapeRegExp(work)}/([A-Za-z0-9_-]{1,64})/([A-Za-z0-9][A-Za-z0-9_]{0,63})/(${UUID})$`)
  const match = typeof cwd === 'string' ? shape.exec(cwd) : null
  if (!match || match[1] !== env.APP_TENANT_ID) {
    throw new FenceError('file tools are unavailable in this process', 'APP_FS_NO_WORKSPACE')
  }
  return { tenant_id: match[1], agent_name: match[2], process_id: match[3] }
}

/** ino:size:mtime of an lstat/stat with bigint: changes on any write we can see. */
export const versionOf = st => `${st.ino}:${st.size}:${st.mtimeNs}`

export async function openWorkspace(cwd, { env = process.env, work = WORK, agents = AGENTS } = {}) {
  const ids = processIds(cwd, { env, work })
  // app-agent makes the root with mkdir: a root reached through a link is not one.
  if ((await realpath(cwd).catch(() => undefined)) !== cwd) throw new FenceError('file tools are unavailable in this process', 'APP_FS_NO_WORKSPACE')
  let template
  try {
    template = await realpath(join(agents, ids.agent_name, 'workspace'))
  } catch {
    template = undefined
  }
  return new Workspace(ids, cwd, template)
}

export class Workspace {
  constructor(ids, root, template) {
    this.ids = ids
    this.root = root
    this.template = template
  }

  /** Model-facing path of an absolute one inside the root. */
  display(abs) {
    return relative(this.root, abs) || '.'
  }

  /** Normalise without touching the disk; anything outside the root is "not found". */
  lexical(path) {
    if (typeof path !== 'string' || path.trim() === '') throw new FenceError('path must be a non-empty string', 'APP_FS_BAD_PATH')
    // eslint-disable-next-line no-control-regex
    if (/[\u0000-\u001f\u007f]/.test(path)) throw new FenceError('path contains control characters', 'APP_FS_BAD_PATH')
    if (Buffer.byteLength(path) > MAX_PATH_BYTES) throw new FenceError(`path longer than ${MAX_PATH_BYTES} bytes`, 'APP_FS_BAD_PATH')
    const abs = isAbsolute(path) ? normalize(path) : resolve(this.root, path)
    const stripped = abs.length > 1 && abs.endsWith(sep) ? abs.slice(0, -1) : abs
    if (!under(stripped, this.root)) throw notFound(path)
    const rel = relative(this.root, stripped)
    if (rel.split(sep).some(part => Buffer.byteLength(part) > MAX_NAME_BYTES)) {
      throw new FenceError(`a file or folder name is longer than ${MAX_NAME_BYTES} bytes`, 'APP_FS_BAD_PATH')
    }
    return { abs: stripped, rel }
  }

  /** Inside the root, or inside this agent's template (read-only). */
  readable(real) {
    return under(real, this.root) || (this.template !== undefined && under(real, this.template))
  }

  /** For reads: follows links, but the real target must stay readable. */
  async resolveRead(path) {
    const { abs, rel } = this.lexical(path)
    let real
    try {
      real = await realpath(abs)
    } catch {
      throw notFound(path)
    }
    if (!this.readable(real)) throw notFound(path)
    return { abs, rel: rel || '.', real }
  }

  /**
   * For changes: no component may be a link (the only links are into the
   * read-only template), and no component may be a non-directory. The leaf may
   * be missing, and so may its parents (ensureParent creates them).
   * @param linkLeaf - accept a link as the leaf itself (trash removes the link, never its target).
   * @param internal - our own writes into .dumps/.trash and .dumps/.patch.
   * @returns missing: how many path components do not exist yet (they count as new entries).
   */
  async resolveMutation(path, { linkLeaf = false, internal = false } = {}) {
    const { abs, rel } = this.lexical(path)
    if (rel === '') throw new FenceError('cannot change the workspace itself', 'APP_FS_ROOT')
    if (!internal && reserved(rel)) throw new FenceError(`cannot change "${rel}": it holds the trash and patch receipts`, 'APP_FS_PROTECTED')
    const parts = rel.split(sep)
    let current = this.root
    for (let i = 0; i < parts.length; i++) {
      current = join(current, parts[i])
      let st
      try {
        st = await lstat(current, { bigint: true })
      } catch (error) {
        if (error.code === 'ENOENT') return { abs, rel, leaf: undefined, missing: parts.length - i }
        throw error
      }
      const shown = relative(this.root, current)
      const last = i === parts.length - 1
      if (st.isSymbolicLink() && !(last && linkLeaf)) throw readOnly(shown)
      if (last) return { abs, rel, leaf: st, missing: 0 }
      if (!st.isDirectory()) throw new FenceError(`"${shown}" is not a directory`, 'APP_FS_NOT_DIRECTORY')
    }
    throw new FenceError('unreachable', 'APP_FS_BAD_PATH')
  }

  /** Create the leaf's missing parents. Safe after resolveMutation: no component is a link. */
  async ensureParent(abs) {
    await mkdir(dirname(abs), { recursive: true })
  }

  /** Version of a path inside the root, without following a link; null when absent. */
  async stamp(abs) {
    try {
      return versionOf(await lstat(abs, { bigint: true }))
    } catch (error) {
      // ENOTDIR: a parent became a file, so this path cannot exist either.
      if (error.code === 'ENOENT' || error.code === 'ENOTDIR') return null
      throw error
    }
  }

  /**
   * Node's own errors (ENOENT, EEXIST…) carry absolute paths, and with them the
   * tenant id. Ours (FenceError, or wrapping one) echo only the model's input
   * or a relative path and keep their wording: an escape must read like a
   * missing file. Every message that reaches the model goes through here.
   */
  scrub(error) {
    if (!(error instanceof Error)) return String(error)
    let message = error.message.replaceAll(`${this.root}/`, '').replaceAll(this.root, '.')
    if (this.template) message = message.replaceAll(`${this.template}/`, '').replaceAll(this.template, '.')
    const ours = error instanceof FenceError || error.cause instanceof FenceError
    if (!ours && message.includes(WORK)) message = 'file operation failed'
    return message
  }

  /** Bytes and entries in the workspace, links not followed (the template is not ours to count). */
  async usage() {
    let bytes = 0
    let entries = 0
    const walk = async dir => {
      for (const entry of await readdir(dir, { withFileTypes: true })) {
        if (++entries > MAX_WORKSPACE_ENTRIES) return
        const path = join(dir, entry.name)
        if (entry.isDirectory()) await walk(path)
        else if (entry.isFile()) bytes += (await lstat(path)).size
      }
    }
    await walk(this.root)
    return { bytes, entries }
  }

  /** Refuse a change that would grow the workspace past its quota. */
  async assertFits(growBytes, newEntries = 1) {
    const { bytes, entries } = await this.usage()
    if (entries + newEntries > MAX_WORKSPACE_ENTRIES) {
      throw new FenceError(`workspace full: at most ${MAX_WORKSPACE_ENTRIES} files and folders`, 'APP_FS_QUOTA')
    }
    if (bytes + growBytes > MAX_WORKSPACE_BYTES) {
      throw new FenceError(`workspace full: at most ${MAX_WORKSPACE_BYTES / 1024 / 1024} MiB; trash files you no longer need`, 'APP_FS_QUOTA')
    }
  }
}

/**
 * Replace or create a file through a fresh temp file and a rename in the same
 * directory: readers never see half a file, and neither step follows a link
 * (O_EXCL on the temp, rename replaces a link instead of writing through it).
 */
export async function atomicWrite(abs, content) {
  const temp = join(dirname(abs), `.app-tmp-${randomBytes(6).toString('hex')}`)
  await writeFile(temp, content, { flag: 'wx', mode: 0o644 })
  try {
    await rename(temp, abs)
  } catch (error) {
    await rm(temp, { force: true })
    throw error
  }
}