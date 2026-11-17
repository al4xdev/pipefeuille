/**
 * Developer dsh plugin: `telemetry_sql` and `telemetry_schema`, read-only, over
 * the DuckDB caches `app-telemetry sync` builds from the harness's dsh sessions.
 * For the developer's own dsh session only: it is never installed in the
 * harness image or inserted into a product agent's profile (README.md).
 *
 * dsh resolves this plugin from the developer's profile, but its imports
 * resolve from this folder's real path (tools/telemetry), where dsh is not
 * installed. So `@deepseek-ai/dsh-tools` is taken from the running dsh
 * (process.argv[1] is dsh's own bin), the one copy whose tool shape the host
 * accepts; and DuckDB from tools/telemetry/node_modules, through ../src/db.js.
 *
 * @module dsh-plugin-app-telemetry-sql
 */

import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'
import { DEFAULTS, schema, sql } from './tools.js'

export const name = 'app-telemetry-sql'
export const inject = ['tools']

function hostModule(id) {
  for (const base of [process.argv[1], import.meta.url]) {
    try {
      return createRequire(base).resolve(id)
    } catch {
      // try the next base
    }
  }
  throw new Error(`app-telemetry-sql: ${id} not found from the running dsh (${process.argv[1]}); load this plugin from a dsh session`)
}
const { defineTool } = await import(pathToFileURL(hostModule('@deepseek-ai/dsh-tools')).href)

const text = { schema: { type: 'string' }, render: (_args, value) => [{ type: 'text', text: value }] }
const cacheParameter = {
  type: 'string',
  description: `Cache name (a file app-telemetry sync wrote: local, dir-<hash>). Defaults to ${DEFAULTS.cache}. telemetry_schema lists them.`,
}

/** config: { cache?, cacheDir?, maxRows?, maxChars? } from the profile entry. */
export function apply(ctx, config = {}) {
  ctx.tools.register(defineTool({
    name: 'telemetry_sql',
    description: 'Run one read-only SQL query (DuckDB dialect) over the agent-session telemetry cache: tables sessions, events, rows, hotspots, tool_calls, model_calls, turns. Only SELECT, WITH, FROM, SHOW, DESCRIBE, SUMMARIZE, EXPLAIN; writes, file access, settings and other databases are refused. Read JSON columns with json_extract_string(data, \'$.path\'). Returns JSON lines.',
    parameters: {
      query: { type: 'string', required: true, description: 'One SQL query.' },
      cache: cacheParameter,
    },
    output: text,
    isConcurrencySafe: () => true,
    execute: async (args, exec) => {
      exec?.signal?.throwIfAborted()
      return sql(args, config)
    },
  }))
  ctx.tools.register(defineTool({
    name: 'telemetry_schema',
    description: 'Describe the agent-session telemetry cache: the caches present, then one JSON line per table with its row count, meaning and columns (name, type, meaning).',
    parameters: { cache: cacheParameter },
    output: text,
    isConcurrencySafe: () => true,
    execute: async (args, exec) => {
      exec?.signal?.throwIfAborted()
      return schema(args, config)
    },
  }))
}
