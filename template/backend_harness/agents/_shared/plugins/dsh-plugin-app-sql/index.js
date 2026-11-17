/**
 * Opt-in `sql` tool: DuckDB queries over files of the process workspace. An
 * agent gets it by listing `sql` in the tools.shared of agents/<name>/agent.yml:
 * the image build then inserts this plugin into that agent's profile
 * (app_<name>), and APP_TOOLS, checked by dsh-plugin-app-tools, is checked again
 * here. `sql` is declared in package.json (`harness.tools`), which is where
 * dsh-plugin-app-tools learns it.
 *
 * @module dsh-plugin-app-sql
 */

import { defineTool } from '@deepseek-ai/dsh-tools'
import { openWorkspace } from 'dsh-plugin-app-fs/workspace'
import { selectTools } from 'dsh-plugin-app-tools'
import { LIMITS, READER_OPTIONS, Slots, sql } from './sql.js'

export const name = 'app-sql'
export const inject = ['tools', 'systemPrompt']

const GUIDANCE = [
  'The sql tool runs DuckDB SQL over files of your workspace, loaded as tables from the files you list in `tables`. The query itself cannot open files or the network.',
  'Check what a file loaded as with DESCRIBE <table> (column types) or SELECT * FROM <table> LIMIT 5. If types or values come out wrong (e.g. ; separators, decimal commas, dd/mm/yyyy dates, latin-1 text), set that table\'s reader options; for anything else, load it with all_varchar and convert in SQL (TRY_CAST, strptime, replace).',
  'Keep memory low: select only the columns you need, filter and aggregate in SQL, and return few rows. Larger work spills to disk within memory_mb.',
].join('\n')

const OPTION_HELP = {
  format: 'Reader to use. Defaults to auto: by content (Parquet, JSON, else delimited text).',
  delimiter: 'Field separator, e.g. ";" or "\\t". Default: sniffed.',
  quote: 'Quote character. Default: sniffed.',
  escape: 'Escape character. Default: sniffed.',
  header: 'Whether the first line holds column names. Default: sniffed.',
  skip: 'Lines to skip before the data (or header).',
  decimal_separator: 'Decimal separator of numbers. Default ".".',
  thousands: 'Thousands separator to ignore in numbers, e.g. "." for 1.234,56.',
  encoding: 'Text encoding. Default utf-8; latin-1 also covers most Windows files.',
  dateformat: 'strptime format of dates, e.g. "%d/%m/%Y".',
  timestampformat: 'strptime format of timestamps, e.g. "%d/%m/%Y %H:%M:%S".',
  nullstr: 'Text that means NULL, e.g. "-" or "NA".',
  all_varchar: 'Load every column as text, to convert in SQL yourself.',
}
const TABLE = {
  type: 'object',
  properties: {
    path: { type: 'string', required: true, description: 'File, relative to your workspace.' },
    ...Object.fromEntries(Object.entries(READER_OPTIONS).map(([key, spec]) => [key, {
      type: spec.type,
      ...(spec.values && { enum: spec.values }),
      description: OPTION_HELP[key],
    }])),
  },
  additionalProperties: false,
}

export function apply(ctx) {
  // app-fs logs a bad APP_TOOLS once; here it just means no tool.
  if (!selectTools(process.env.APP_TOOLS).tools.has('sql')) return

  const workspaces = new Map()
  const workspaceOf = exec => {
    const cwd = exec.agent?.session.header.cwd
    if (!workspaces.has(cwd)) {
      workspaces.set(cwd, openWorkspace(cwd))
      workspaces.get(cwd).catch(() => workspaces.delete(cwd))
    }
    return workspaces.get(cwd)
  }
  const slots = new Slots(LIMITS.parallel)

  ctx.systemPrompt.section({
    name: 'tool:app-sql',
    order: ctx.systemPrompt.getSectionOrder('TOOL_READ'),
    text: () => GUIDANCE,
  })
  ctx.tools.register(defineTool({
    name: 'sql',
    description: 'Run a DuckDB SQL query over workspace files and return the result as CSV. Files are read by content: Parquet, JSON (an array or one object per line), or delimited text (CSV, TSV and others). Several calls may run in parallel.',
    parameters: {
      query: { type: 'string', required: true, description: 'DuckDB SQL. SELECT, EXPLAIN, PIVOT, and CREATE/INSERT/UPDATE/DELETE/DROP of scratch tables that live only for this call; the last statement\'s result is returned.' },
      tables: { type: 'array', items: TABLE, description: `Files to load, at most ${LIMITS.tables}: [{"path": "data/sales-2024.csv"}], plus reader options only where a file needs them (they apply to delimited text). Each becomes a table named after its file name without the extension, other characters as _ (data/sales-2024.csv is table sales_2024; a leading digit gets t_).` },
      memory_mb: { type: 'number', description: `Memory limit in MB, ${LIMITS.memory.min}-${LIMITS.memory.max}. Defaults to ${LIMITS.memory.default}; raise it only if a query fails for memory.` },
      timeout_s: { type: 'number', description: `Seconds before the query is stopped, up to ${LIMITS.timeout.max}. Defaults to ${LIMITS.timeout.default}.` },
      max_rows: { type: 'number', description: `Rows to return, up to ${LIMITS.rows.max}. Defaults to ${LIMITS.rows.default}; the total row count is always reported.` },
    },
    isConcurrencySafe: () => true,
    output: { schema: { type: 'string' }, render: (_args, value) => [{ type: 'text', text: value }] },
    execute: async (args, exec) => {
      exec.signal?.throwIfAborted()
      const ws = await workspaceOf(exec)
      try {
        return await sql(ws, slots, args, exec.signal)
      } catch (error) {
        if (!(error instanceof Error)) throw error
        const message = ws.scrub(error)
        if (message === error.message) throw error
        throw Object.assign(new Error(message), { code: error.code })
      }
    },
  }))
}