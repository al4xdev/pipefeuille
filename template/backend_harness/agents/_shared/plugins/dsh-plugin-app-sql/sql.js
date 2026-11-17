/**
 * The sql tool: DuckDB over workspace files, one locked-down worker.py process
 * per call (see there for the DuckDB lock-down).
 *
 * This side is the fence: every table path goes through app-fs's workspace.js
 * (the workspace, or the read-only template), the worker gets only canonical
 * paths, an empty environment and a timeout, and its messages are scrubbed of
 * host paths like every other tool's.
 *
 * @module dsh-plugin-app-sql/sql
 */

import { spawn } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { mkdir, rm, stat } from 'node:fs/promises'
import { basename, extname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { FenceError } from 'dsh-plugin-app-fs/workspace'

// The worker runs on the harness server's venv (backend_harness/server: duckdb is one of
// its locked dependencies), so the template keeps one Python project for the whole
// runtime layer instead of a second one inside this plugin.
export const PYTHON = '/opt/app/server/.venv/bin/python'
const WORKER = fileURLToPath(new URL('worker.py', import.meta.url))
// Spill folders. DuckDB adds temp_directory, made absolute, to allowed_directories
// when external access is switched off: the agent's SQL can read it and every
// catalog query shows it. Inside the workspace that path holds the tenant id, so
// each call spills into a random folder here instead, removed after the call.
export const SPILL = '/tmp/app-sql'

export const LIMITS = {
  tables: 16,
  queryBytes: 100 * 1024,
  // /tmp may be RAM (a tmpfs): the default keeps a call near the ~192 MiB an agent
  // slot of the harness server assumes. 128 MB was measured to load and sort a 64 MiB CSV (the
  // workspace maximum) with 1 thread; DuckDB itself adds ~75 MB on top.
  memory: { min: 64, default: 128, max: 1024 },
  timeout: { min: 1, default: 60, max: 300 },
  rows: { min: 1, default: 200, max: 2000 },
  parallel: 4,
  stdoutBytes: 256 * 1024,
}

/** The table a file loads as: its name without extension, other characters as _ (sales-2024.csv: sales_2024). */
export function tableName(path) {
  const name = basename(path, extname(path)).replace(/[^A-Za-z0-9_]/g, '_')
  return (/^[0-9]/.test(name) ? `t_${name}` : name).slice(0, 63)
}

function integer(value, name, { min, default: fallback, max }) {
  if (value === undefined) return fallback
  if (!Number.isInteger(value) || value < min || value > max) throw new Error(`${name} must be an integer from ${min} to ${max}`)
  return value
}

// Reader options per table, a fixed list: worker.py binds each value as a
// parameter of read_csv, never as SQL text. Anything a file needs beyond these,
// the agent gets with all_varchar and casts in SQL.
const text = max => ({ type: 'string', max })
const oneOf = (...values) => ({ type: 'string', values })
export const READER_OPTIONS = {
  format: oneOf('auto', 'csv', 'json', 'parquet'),
  delimiter: text(4),
  quote: text(1),
  escape: text(1),
  header: { type: 'boolean' },
  skip: { type: 'integer', min: 0, max: 1_000_000 },
  decimal_separator: oneOf('.', ','),
  thousands: text(1),
  encoding: oneOf('utf-8', 'utf-16', 'latin-1'),
  dateformat: text(64),
  timestampformat: text(64),
  nullstr: text(64),
  all_varchar: { type: 'boolean' },
}

function readerOptions(entry, rel) {
  const options = {}
  for (const [key, value] of Object.entries(entry)) {
    if (key === 'path') continue
    const spec = Object.hasOwn(READER_OPTIONS, key) ? READER_OPTIONS[key] : undefined
    if (!spec) throw new Error(`${rel}: unknown option ${key}; use ${Object.keys(READER_OPTIONS).join(', ')}`)
    const bad = spec.type === 'integer' ? !Number.isInteger(value) || value < spec.min || value > spec.max
      : spec.type === 'boolean' ? typeof value !== 'boolean'
        : typeof value !== 'string' || (spec.values ? !spec.values.includes(value)
          // Tab is a real delimiter; other control characters are not.
          : !value.length || value.length > spec.max || /[\0-\x08\n-\x1f\x7f]/.test(value))
    if (bad) throw new Error(`${rel}: bad ${key}; expected ${spec.values ? spec.values.join(' or ') : spec.max ? `text of at most ${spec.max} characters` : spec.type}`)
    if (key !== 'format' || value !== 'auto') options[key] = value
  }
  return options
}

/** At most `size` workers at once per agent process; the rest wait their turn. */
export class Slots {
  #free
  #waiting = []
  constructor(size) {
    this.#free = size
  }

  async run(fn) {
    if (this.#free > 0) this.#free -= 1
    else await new Promise(resolve => this.#waiting.push(resolve))
    try {
      return await fn()
    } finally {
      const next = this.#waiting.shift()
      if (next) next()
      else this.#free += 1
    }
  }
}

async function resolveTables(ws, tables) {
  if (tables === undefined) return []
  const isEntry = entry => typeof entry === 'object' && entry !== null && !Array.isArray(entry) && typeof entry.path === 'string'
  if (!Array.isArray(tables) || !tables.every(isEntry)) throw new Error('tables must be a list of {"path": "file", ...reader options}')
  if (tables.length > LIMITS.tables) throw new Error(`at most ${LIMITS.tables} tables`)
  const out = []
  const names = new Map()
  for (const entry of tables) {
    const { rel, real } = await ws.resolveRead(entry.path)
    const options = readerOptions(entry, rel)
    // The format comes from the content, in worker.py.
    if (!(await stat(real)).isFile()) throw new FenceError(`"${rel}" is not a file`, 'APP_FS_NOT_FOUND')
    const name = tableName(rel)
    // DuckDB names are case-insensitive.
    const clash = names.get(name.toLowerCase())
    if (clash !== undefined) throw new FenceError(`"${clash}" and "${rel}" would both be table ${name}; query them in separate calls`, 'APP_SQL_TABLE_NAME')
    names.set(name.toLowerCase(), rel)
    out.push({ name, path: real, shown: rel, options })
  }
  return out
}

function runWorker(cwd, request, timeoutMs, signal) {
  return new Promise((resolve, reject) => {
    // Empty env: no APP_TENANT_ID, tokens or credentials reach the worker.
    const child = spawn(PYTHON, ['-I', WORKER], { cwd, env: {}, stdio: ['pipe', 'pipe', 'pipe'] })
    const chunks = []
    let bytes = 0
    let stderr = ''
    let reason
    const stop = why => {
      reason ??= why
      child.kill('SIGKILL')
    }
    const timer = setTimeout(() => stop(`the query ran past ${timeoutMs / 1000} s and was stopped; aggregate, filter or LIMIT it`), timeoutMs)
    const onAbort = () => stop('the call was cancelled')
    signal?.addEventListener('abort', onAbort, { once: true })
    child.stdout.on('data', chunk => {
      bytes += chunk.length
      if (bytes > LIMITS.stdoutBytes) stop('the query output was too large')
      else chunks.push(chunk)
    })
    child.stderr.on('data', chunk => {
      if (stderr.length < 4096) stderr += chunk
    })
    child.on('error', error => stop(error.message))
    child.on('close', code => {
      clearTimeout(timer)
      signal?.removeEventListener('abort', onAbort)
      if (reason) return reject(new FenceError(reason, 'APP_SQL_STOPPED'))
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString('utf8')))
      } catch {
        // A crash (e.g. the kernel's OOM kill): its traceback is for our logs, not the model.
        console.error(JSON.stringify({ severity: 'ERROR', component: 'app-sql', event: 'worker_failed', code, stderr: stderr.slice(-1024) }))
        reject(new FenceError(`the query process failed (exit ${code}); lower memory_mb usage or simplify the query`, 'APP_SQL_FAILED'))
      }
    })
    child.stdin.end(JSON.stringify(request))
  })
}

export async function sql(ws, slots, args, signal) {
  const { query } = args
  if (typeof query !== 'string' || !query.trim()) throw new Error('query must be a non-empty string')
  if (Buffer.byteLength(query) > LIMITS.queryBytes) throw new Error(`query must be at most ${LIMITS.queryBytes / 1024} KiB`)
  const memory = integer(args.memory_mb, 'memory_mb', LIMITS.memory)
  const timeout = integer(args.timeout_s, 'timeout_s', LIMITS.timeout)
  const maxRows = integer(args.max_rows, 'max_rows', LIMITS.rows)
  const tables = await resolveTables(ws, args.tables)

  return slots.run(async () => {
    await mkdir(SPILL, { recursive: true, mode: 0o700 })
    const tempDir = join(SPILL, randomBytes(16).toString('hex'))
    await mkdir(tempDir, { mode: 0o700 })
    try {
      const out = await runWorker(ws.root, { query, tables, memory_mb: memory, max_rows: maxRows, temp_dir: tempDir }, timeout * 1000, signal)
      if (!out.ok) throw new FenceError(out.error, 'APP_SQL_ERROR')
      const more = out.total > out.shown ? `; aggregate, filter or LIMIT to see the rest` : ''
      return `${out.csv}\n(${out.shown} of ${out.total} rows${more})`
    } finally {
      await rm(tempDir, { recursive: true, force: true })
    }
  })
}