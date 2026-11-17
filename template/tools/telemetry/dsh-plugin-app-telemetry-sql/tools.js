/**
 * The two tools without dsh: which cache a call reads, and what it answers.
 * index.js only registers them. Every query goes through the telemetry tool's
 * own guard (`query` in ../src/db.js: one private read-only copy per query,
 * external access off, extension autoload off, configuration locked, and only
 * SELECT-like statements), so this plugin adds no second, weaker fence.
 *
 * @module dsh-plugin-app-telemetry-sql/tools
 */

import { existsSync, readdirSync } from 'node:fs'
import { join } from 'node:path'
import { cacheRoot } from '../src/cache.js'

// A cache is named, never pathed: the model picks among the files `app-telemetry
// sync` wrote into the cache folder (local, dir-1a2b3c4d), so no argument can
// point DuckDB at another file.
const CACHE_NAME = /^[a-z0-9][a-z0-9-]{0,63}$/
export const DEFAULTS = { cache: 'local', maxRows: 200, maxChars: 60_000 }

/** The cache files present, by name, sorted. */
export function cachesIn(dir) {
  return existsSync(dir)
    ? readdirSync(dir).filter(file => file.endsWith('.duckdb')).map(file => file.slice(0, -'.duckdb'.length)).filter(name => CACHE_NAME.test(name)).sort()
    : []
}

/** The path of a named cache, or an Error that says which ones exist. */
export function cachePathOf(name, { cacheDir = cacheRoot(), cache = DEFAULTS.cache } = {}) {
  const chosen = name ?? cache
  if (typeof chosen !== 'string' || !CACHE_NAME.test(chosen))
    throw new Error(`cache: a cache name such as local or dir-1a2b3c4d, not a path (got ${JSON.stringify(chosen)})`)
  const path = join(cacheDir, `${chosen}.duckdb`)
  if (!existsSync(path)) {
    const found = cachesIn(cacheDir)
    throw new Error(`no cache ${chosen}: the developer runs \`app-telemetry sync\` first (caches here: ${found.length ? found.join(', ') : 'none'})`)
  }
  return path
}

/** JSON lines, cut at maxRows rows or maxChars characters, with a line saying so. */
export function render(rows, { maxRows = DEFAULTS.maxRows, maxChars = DEFAULTS.maxChars } = {}) {
  const lines = []
  let size = 0
  for (const [index, row] of rows.entries()) {
    const line = JSON.stringify(row)
    if (index >= maxRows || size + line.length + 1 > maxChars) {
      lines.push(JSON.stringify({ truncated: true, shown: index, rows: rows.length, hint: 'add LIMIT, or aggregate' }))
      break
    }
    lines.push(line)
    size += line.length + 1
  }
  return lines.length ? lines.join('\n') : '(no rows)'
}

// DuckDB is a native addon: loaded on the first call, so a profile whose
// tools/telemetry has no node_modules yet still boots, and the call says why.
async function db() {
  try {
    return await import('../src/db.js')
  } catch (error) {
    throw new Error(`the telemetry tool's dependencies are missing: run \`npm ci\` in tools/telemetry (${error.message})`)
  }
}

export async function sql({ query, cache }, config = {}) {
  if (typeof query !== 'string' || query.trim() === '') throw new Error('query: give one read-only SQL query')
  const { query: run } = await db()
  return render(await run(cachePathOf(cache, config), query), config)
}

export async function schema({ cache }, config = {}) {
  const { describeCache } = await db()
  const path = cachePathOf(cache, config)
  const head = { cache: cache ?? config.cache ?? DEFAULTS.cache, caches: cachesIn(config.cacheDir ?? cacheRoot()) }
  return [JSON.stringify(head), ...(await describeCache(path)).map(table => JSON.stringify(table))].join('\n')
}
