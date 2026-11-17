// Command line. A command runs headless (JSON on stdout, for agents); no command
// opens the TUI on a terminal and falls back to `sessions` when piped.
import { createHash } from 'node:crypto';
import { join, resolve } from 'node:path';
import { parseArgs } from 'node:util';
import { makeFilter, parseDate } from './filters.js';
import { cacheRoot } from './cache.js';
import { loadSession, openSource } from './sources.js';
import { aggregate, buildTrajectory, inspectNode } from './vendor/dsh-adapter/trajectory/index.js';

export const USAGE = `usage: app-telemetry [source] [filters] [command]

commands (headless, JSON lines on stdout):
  sessions                 the sessions matching the filters (default when piped)
  trajectory SESSION_ID    the trajectory fold of one session: totals, hotspots, rows
                           (--detail adds each row's input/output)
  sync                     read the matching sessions into the local DuckDB cache and
                           prepare their features (the TUI's numbers) as tables; incremental
  sql "QUERY"              query the cache offline, read-only (SELECT, DESCRIBE, SUMMARIZE...);
                           --sync syncs the matching sessions first
  schema                   the cache's tables: row counts, columns, types, meaning
  (none, on a terminal)    the TUI: sessions list, Enter opens the trajectory

source (read-only; nothing is written back):
  --local                  the running harness container app-harness-local
                           (backend_harness/docker.sh serve); the default
  --dir PATH               a host copy of the dsh sessions (docker.sh SESSIONS=PATH)

filters (exact or prefix):
  --tenant_id ID  --agent_name NAME  --process_id ID  --session_id ID
  --date YYYY-MM-DD | FROM..TO       on started_at, UTC; either side may be empty

options:
  --db PATH                cache file (default ~/.cache/app-telemetry/<local|dir-hash>.duckdb)
  --headless               never open the TUI
`;

const OPTIONS = {
    local: { type: 'boolean', default: false },
    dir: { type: 'string' },
    tenant_id: { type: 'string' },
    agent_name: { type: 'string' },
    process_id: { type: 'string' },
    session_id: { type: 'string' },
    date: { type: 'string' },
    db: { type: 'string' },
    detail: { type: 'boolean', default: false },
    sync: { type: 'boolean', default: false },
    headless: { type: 'boolean', default: false },
    help: { type: 'boolean', short: 'h', default: false },
};

export class UsageError extends Error { }

export function parseCli(argv) {
    let parsed;
    try {
        parsed = parseArgs({ args: argv, options: OPTIONS, allowPositionals: true, strict: true });
    }
    catch (error) {
        throw new UsageError(error.message);
    }
    const { values, positionals } = parsed;
    if (values.local && values.dir !== undefined)
        throw new UsageError('--local and --dir are two sources: pick one');
    try {
        parseDate(values.date);
    }
    catch (error) {
        throw new UsageError(error.message);
    }
    return { options: values, command: positionals[0], args: positionals.slice(1) };
}

/** One cache per source, named from the flags alone: sql/schema stay offline. */
export function cachePath(options) {
    if (options.db !== undefined)
        return options.db;
    if (options.dir !== undefined)
        return join(cacheRoot(), `dir-${createHash('sha256').update(resolve(options.dir)).digest('hex').slice(0, 8)}.duckdb`);
    return join(cacheRoot(), 'local.duckdb');
}

async function sync(options) {
    const { syncCache } = await import('./db.js');
    const { source, sessions } = await selectSessions(options);
    return syncCache(cachePath(options), sessions, session => loadSession(source, session));
}

/** Sessions of the source that pass the filters (listing only: first frames, nothing decoded whole). */
export async function selectSessions(options) {
    const source = await openSource(options);
    const keep = makeFilter(options);
    const sessions = (await source.list()).filter(keep);
    return { source, sessions };
}

/** The row agents see for a session: identity and size, not where its copy sits on disk. */
export function sessionRow(session) {
    const { file, header, events, ...row } = session;
    return row;
}

export function trajectoryOf(events, { detail = false } = {}) {
    const build = buildTrajectory(events);
    const agg = aggregate(build, 'duration');
    const nodes = build.nodes.map(node => (detail ? { ...node, inspect: inspectNode(node, events) } : node));
    return { totals: agg.totals, hotspots: { tools: agg.tools, model: agg.model, turns: agg.turns }, nodes };
}

function print(value) {
    process.stdout.write(JSON.stringify(value) + '\n');
}

export async function runHeadless(command, args, options) {
    switch (command ?? 'sessions') {
        case 'sessions': {
            const { sessions } = await selectSessions(options);
            for (const session of sessions)
                print(sessionRow(session));
            return;
        }
        case 'trajectory': {
            const id = args[0] ?? options.session_id;
            if (id === undefined)
                throw new UsageError('trajectory: give a SESSION_ID (or a unique prefix)');
            const { source, sessions } = await selectSessions({ ...options, session_id: id });
            if (sessions.length !== 1)
                throw new Error(sessions.length === 0
                    ? `trajectory: no session ${id} in ${source.label}`
                    : `trajectory: ${id} matches ${sessions.length} sessions: ${sessions.map(s => s.session_id).join(', ')}`);
            const session = await loadSession(source, sessions[0]);
            print({ session: sessionRow(session), ...trajectoryOf(session.events, { detail: options.detail }) });
            return;
        }
        case 'sync':
            print(await sync(options));
            return;
        case 'sql': {
            const sql = args.join(' ').trim();
            if (sql === '')
                throw new UsageError('sql: give a query, e.g. sql "SELECT * FROM turns"; see `app-telemetry schema`');
            if (options.sync)
                await sync(options);
            const { query } = await import('./db.js');
            for (const row of await query(cachePath(options), sql))
                print(row);
            return;
        }
        case 'schema': {
            const { describeCache } = await import('./db.js');
            for (const table of await describeCache(cachePath(options)))
                print(table);
            return;
        }
        default:
            throw new UsageError(`unknown command: ${command}`);
    }
}