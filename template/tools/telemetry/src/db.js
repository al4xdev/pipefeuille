// The agents' feature cache: a local DuckDB file of the synced sessions, with the
// trajectory fold's numbers (the TUI's screen data) materialised as tables, so a
// query matches what a human sees. Headless only: the TUI never imports this.
//
// sync is incremental (a session is re-decoded only when its byte count changed)
// and accumulating (a filtered sync never drops other sessions). Queries are
// SELECT-like statements only, on a sandboxed private copy (see openSandbox);
// DuckDB's own SHOW / DESCRIBE / SUMMARIZE stay available.
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { DuckDBInstance, StatementType } from '@duckdb/node-api';
import { aggregate, buildTrajectory, burstDurationMs, burstErrors, burstRunning } from './vendor/dsh-adapter/trajectory/index.js';

// [name, type, comment]. Order = column order = the NDJSON loaded into it.
const BASE = {
    sessions: ['one row per synced dsh session; identity from its path, totals from the trajectory fold', [
        ['session_id', 'VARCHAR', 'session-<uuid>, the dsh session id (app-agent resume passes it to dsh --session-id)'],
        ['source', 'VARCHAR', 'local (--local, the harness container) | dir (--dir PATH)'],
        ['tenant_id', 'VARCHAR', 'tenant the process ran for (APP_TENANT_ID)'],
        ['agent_name', 'VARCHAR', 'agent folder under backend_harness/agents/'],
        ['process_id', 'VARCHAR', 'uuid the harness server generated for the dispatch'],
        ['started_at', 'TIMESTAMPTZ', 'session header createdAt (the file mtime when the header does not decode)'],
        ['updated_at', 'TIMESTAMPTZ', 'session file last written'],
        ['bytes', 'BIGINT', 'compressed size of the session log; a change triggers a re-sync'],
        ['events', 'INTEGER', 'events in the log'],
        ['cwd', 'VARCHAR', 'workspace of the process (/tmp/app-work/<tenant>/<agent>/<process>)'],
        ['model', 'VARCHAR', 'model of the last request'],
        ['turns', 'INTEGER', 'fold totals (TUI header): turns'],
        ['steps', 'INTEGER', 'model steps'],
        ['rows', 'INTEGER', 'trajectory ledger rows'],
        ['calls', 'INTEGER', 'tool calls'],
        ['errors', 'INTEGER', 'failed tool calls / steps'],
        ['retries', 'INTEGER', 'request retries'],
        ['span_ms', 'BIGINT', 'wall time from first to last event'],
        ['tool_ms', 'BIGINT', 'time inside tools'],
        ['decode_ms', 'BIGINT', 'time streaming model output'],
        ['ttft_ms', 'BIGINT', 'summed time to first token'],
        ['retry_ms', 'BIGINT', 'time lost to retries'],
        ['input_tokens', 'BIGINT', 'uncached input tokens'],
        ['output_tokens', 'BIGINT', 'output tokens'],
        ['think_tokens', 'BIGINT', 'reasoning tokens'],
        ['cache_read_tokens', 'BIGINT', 'cached input tokens read'],
        ['cache_write_tokens', 'BIGINT', 'cached input tokens written'],
    ]],
    events: ['the raw session log, one dsh event per row', [
        ['session_id', 'VARCHAR', 'sessions.session_id'],
        ['seq', 'INTEGER', 'event order within the session'],
        ['type', 'VARCHAR', 'dsh event type (turn/start, tool/call, assistant/message, ...)'],
        ['time', 'TIMESTAMPTZ', 'when it was written'],
        ['turn', 'INTEGER', 'data.turn when the event has one'],
        ['step', 'INTEGER', 'data.step when the event has one'],
        ['data', 'JSON', 'the event payload; read it with json_extract_string(data, \'$.path\') (->> binds looser than = and AND: parenthesise it)'],
    ]],
    rows: ['the Trajectory screen ledger: one fold node per row, in screen order', [
        ['session_id', 'VARCHAR', 'sessions.session_id'],
        ['idx', 'INTEGER', 'row position on the screen'],
        ['seq', 'INTEGER', 'event that opened the row'],
        ['end_seq', 'INTEGER', 'event that closed it (tool result, step end)'],
        ['time', 'TIMESTAMPTZ', 'when the row started'],
        ['kind', 'VARCHAR', 'system | turn | step | user | context | thinking | assistant | tool | ...'],
        ['turn', 'INTEGER', 'turn number'],
        ['step', 'INTEGER', 'step number'],
        ['label', 'VARCHAR', 'row label (tool name, turn N, ...)'],
        ['detail', 'VARCHAR', 'full row text (message, tool arguments)'],
        ['call_id', 'VARCHAR', 'tool call id'],
        ['members', 'INTEGER', 'calls the row stands for: 1, or N for a burst (3+ consecutive calls of one tool shown as one row)'],
        ['status', 'VARCHAR', 'ok | error | running (a burst: error if any member failed)'],
        ['outcome', 'VARCHAR', 'tool result text (NULL for a burst)'],
        ['duration_ms', 'BIGINT', 'row duration (a burst: its members summed)'],
        ['input_tokens', 'BIGINT', 'tokens attributed to the row'],
        ['output_tokens', 'BIGINT', ''],
        ['think_tokens', 'BIGINT', ''],
        ['node', 'JSON', 'the fold node as is'],
    ]],
    hotspots: ['the Hotspot screen: where the time and tokens of a session went', [
        ['session_id', 'VARCHAR', 'sessions.session_id'],
        ['section', 'VARCHAR', 'tools | model | turns'],
        ['label', 'VARCHAR', 'tool name, ttft / decode, or turn N'],
        ['total_ms', 'BIGINT', 'summed duration'],
        ['count', 'INTEGER', 'occurrences'],
        ['tokens', 'BIGINT', 'summed tokens'],
    ]],
};

// Rebuilt from the base tables after every sync. json_extract_string(), not
// ->>: DuckDB's ->> binds looser than = and AND, so `a AND x->>'$.k' = y`
// parses as `(a AND x) ->> ...`.
// tool_calls pairs like the fold: on message.source.callId, with the first
// result after the call (call ids like mock_tool#0 come from a per-adapter
// counter, not a contract, so they may repeat within a session), and an error is
// a result with data.error, as on the screen.
const DERIVED = {
    tool_calls: ['tool calls joined to their results', `
        SELECT c.session_id, c.seq, c.turn, c.step, c.time,
               json_extract_string(c.data, '$.callId') AS call_id,
               json_extract_string(c.data, '$.name') AS name,
               json_extract_string(c.data, '$.arguments') AS arguments,
               r.seq AS result_seq,
               CASE WHEN r.seq IS NOT NULL THEN json_extract(r.data, '$.error') IS NOT NULL END AS is_error,
               json_extract_string(r.data, '$.error.code') AS error_code,
               json_extract_string(r.data, '$.message.isError')::BOOLEAN AS tool_is_error,
               json_extract_string(r.data, '$.message.content[0].text') AS result_text,
               date_diff('millisecond', c.time, r.time) AS duration_ms
        FROM events c
        LEFT JOIN events r ON r.session_id = c.session_id AND r.type = 'tool/result' AND r.seq > c.seq
         AND json_extract_string(r.data, '$.message.source.callId') = json_extract_string(c.data, '$.callId')
        WHERE c.type = 'tool/call'
        QUALIFY row_number() OVER (PARTITION BY c.session_id, c.seq ORDER BY r.seq) = 1`],
    model_calls: ['one row per model response, with the model and its token usage', `
        SELECT a.session_id, a.seq, a.turn, a.step, a.time,
               (SELECT json_extract_string(h.data, '$.header.config.model') FROM events h
                 WHERE h.session_id = a.session_id AND h.type = 'request/header' AND h.seq < a.seq
                 ORDER BY h.seq DESC LIMIT 1) AS model,
               json_extract_string(a.data, '$.usage.inputTokens')::BIGINT AS input_tokens,
               json_extract_string(a.data, '$.usage.outputTokens')::BIGINT AS output_tokens,
               json_extract_string(a.data, '$.usage.reasoningTokens')::BIGINT AS reasoning_tokens,
               json_extract_string(a.data, '$.usage.cacheReadTokens')::BIGINT AS cache_read_tokens,
               array_to_string(list_transform(
                   list_filter(json_extract(a.data, '$.message.content[*]'), b -> json_extract_string(b, '$.type') = 'text'),
                   b -> json_extract_string(b, '$.text')), '') AS text
        FROM events a
        WHERE a.type = 'assistant/message'`],
    turns: ['one row per turn: span, outcome, steps, tools, tokens', `
        SELECT s.session_id, s.turn, s.time AS started_at, e.time AS ended_at,
               date_diff('millisecond', s.time, e.time) AS duration_ms,
               json_extract_string(e.data, '$.reason.kind') AS outcome,
               (SELECT count(*) FROM events x WHERE x.session_id = s.session_id AND x.turn = s.turn AND x.type = 'step/start')::INTEGER AS steps,
               (SELECT count(*) FROM events x WHERE x.session_id = s.session_id AND x.turn = s.turn AND x.type = 'tool/call')::INTEGER AS tool_calls,
               (SELECT sum(input_tokens) FROM model_calls m WHERE m.session_id = s.session_id AND m.turn = s.turn)::BIGINT AS input_tokens,
               (SELECT sum(output_tokens) FROM model_calls m WHERE m.session_id = s.session_id AND m.turn = s.turn)::BIGINT AS output_tokens,
               (SELECT sum(reasoning_tokens) FROM model_calls m WHERE m.session_id = s.session_id AND m.turn = s.turn)::BIGINT AS reasoning_tokens
        FROM events s
        LEFT JOIN events e ON e.session_id = s.session_id AND e.type = 'turn/end' AND e.turn = s.turn
        WHERE s.type = 'turn/start'`],
};

const quote = text => `'${String(text).replaceAll("'", "''")}'`;
const int = value => (Number.isFinite(value) ? Math.round(value) : null);
const iso = ms => (Number.isFinite(ms) ? new Date(ms).toISOString() : null);

/** The base-table rows of one decoded session: what the TUI would compute, flattened. */
export function featureRows(session) {
    const build = buildTrajectory(session.events);
    const { totals, tools, model, turns } = aggregate(build, 'duration');
    const lastHeader = session.events.findLast(event => event.type === 'request/header');
    const id = session.session_id;
    return {
        sessions: [{
            session_id: id, source: session.source, tenant_id: session.tenant_id,
            agent_name: session.agent_name, process_id: session.process_id,
            started_at: session.started_at, updated_at: session.updated_at, bytes: session.bytes,
            events: session.events.length, cwd: session.header?.cwd ?? null,
            model: lastHeader?.data?.header?.config?.model ?? null,
            turns: totals.turns, steps: totals.steps, rows: totals.rows, calls: totals.calls, errors: totals.errors,
            retries: totals.retries, span_ms: int(totals.spanMs), tool_ms: int(totals.toolMs),
            decode_ms: int(totals.decodeMs), ttft_ms: int(totals.ttftMs), retry_ms: int(totals.retryMs),
            input_tokens: totals.tokens.input, output_tokens: totals.tokens.output, think_tokens: totals.tokens.think,
            cache_read_tokens: totals.tokens.cacheRead, cache_write_tokens: totals.tokens.cacheWrite,
        }],
        events: session.events.map(event => ({
            session_id: id, seq: event.seq, type: event.type, time: iso(event.time),
            turn: int(event.data?.turn), step: int(event.data?.step), data: event.data ?? null,
        })),
        // A burst node has no status/duration of its own: the screen reads them
        // off its members with the same helpers.
        rows: build.nodes.map((node, idx) => ({
            session_id: id, idx, seq: node.seq, time: iso(node.time),
            kind: node.kind, turn: int(node.turn), step: int(node.step), label: node.label ?? null,
            detail: typeof node.detail === 'string' ? node.detail : null, call_id: node.callId ?? null,
            ...(node.burst === undefined
                ? {
                    end_seq: node.endSeq ?? null, members: 1, status: node.status ?? null,
                    outcome: typeof node.outcome === 'string' ? node.outcome : null, duration_ms: int(node.durationMs),
                }
                : {
                    end_seq: node.burst.members.at(-1)?.endSeq ?? null, members: node.burst.members.length,
                    status: burstErrors(node.burst) > 0 ? 'error' : burstRunning(node.burst) ? 'running' : 'ok',
                    outcome: null, duration_ms: int(burstDurationMs(node.burst)),
                }),
            input_tokens: int(node.tokens?.input),
            output_tokens: int(node.tokens?.output), think_tokens: int(node.tokens?.think), node,
        })),
        hotspots: Object.entries({ tools, model, turns }).flatMap(([section, entries]) => entries.map(entry => ({
            session_id: id, section, label: entry.label, total_ms: int(entry.totalMs), count: entry.count, tokens: int(entry.tokens),
        }))),
    };
}

async function connect(path, options) {
    const instance = await DuckDBInstance.create(path, options);
    const connection = await instance.connect();
    await connection.run("SET TimeZone = 'UTC'");
    return {
        connection,
        close() {
            connection.closeSync();
            instance.closeSync();
        },
    };
}

/**
 * What the cache holds now: session_id → bytes, and whether its base tables
 * have the columns this version writes. Read-only, so a sync does not lock the
 * cache while it downloads.
 */
async function columnsOf(connection) {
    const columns = new Map();
    for (const row of (await connection.runAndReadAll(
        "SELECT table_name, column_name, data_type FROM duckdb_columns() WHERE database_name = current_database() ORDER BY table_name, column_index"))
        .getRowObjectsJS())
        columns.set(row.table_name, `${columns.get(row.table_name) ?? ''}${row.column_name} ${row.data_type},`);
    return columns;
}

// The base layout as DuckDB spells it (TIMESTAMPTZ reads back as TIMESTAMP WITH
// TIME ZONE), from the same CREATEs on an in-memory db.
async function baseLayout() {
    const { connection, close } = await connect(':memory:');
    try {
        for (const [table, [, columns]] of Object.entries(BASE))
            await connection.run(`CREATE TABLE ${table} (${columns.map(([name, type]) => `${name} ${type}`).join(', ')})`);
        return await columnsOf(connection);
    }
    finally {
        close();
    }
}

async function cacheState(path) {
    if (!existsSync(path))
        return { known: new Map(), outdated: false };
    const expected = await baseLayout();
    const { connection, close } = await connect(path, { access_mode: 'READ_ONLY' });
    try {
        const existing = await columnsOf(connection);
        const outdated = Object.keys(BASE).some(table => existing.has(table) && existing.get(table) !== expected.get(table));
        if (outdated || !existing.has('sessions'))
            return { known: new Map(), outdated };
        const known = new Map((await connection.runAndReadAll('SELECT session_id, bytes FROM sessions'))
            .getRowObjectsJS().map(row => [row.session_id, Number(row.bytes)]));
        return { known, outdated };
    }
    finally {
        close();
    }
}

// A lone UTF-16 surrogate (text cut mid-pair) makes read_json refuse the whole file.
const wellFormed = (_key, value) => (typeof value === 'string' ? value.toWellFormed() : value);

/**
 * Add `sessions` to the cache at `path`. `load(session)` returns the decoded
 * session ({ header, events, ...identity }) and is called only for sessions that
 * are new or changed size. Everything is loaded before the cache is opened for
 * writing, and then changed in one transaction: a failure leaves it as it was.
 */
export async function syncCache(path, sessions, load) {
    mkdirSync(dirname(path), { recursive: true });
    // A cache built by an older version with other columns is rebuilt, not
    // migrated: every session counts as new and is reloaded from the source.
    const { known, outdated } = await cacheState(path);
    const unique = [...new Map(sessions.map(session => [session.session_id, session])).values()];
    const stale = unique.filter(session => known.get(session.session_id) !== session.bytes);
    const tables = { sessions: [], events: [], rows: [], hotspots: [] };
    for (const session of stale) {
        const features = featureRows(await load(session));
        for (const table of Object.keys(tables))
            tables[table].push(...features[table]);
    }
    const { connection, close } = await connect(path);
    const staging = mkdtempSync(join(tmpdir(), 'app-telemetry-sync-'));
    try {
        // One transaction also because each autocommit statement on a file db is an
        // fsync (~140 ms), and the comments alone are ~60 statements.
        await connection.run('BEGIN TRANSACTION');
        try {
            if (outdated)
                for (const table of [...Object.keys(DERIVED), ...Object.keys(BASE)])
                    await connection.run(`DROP TABLE IF EXISTS ${table}`);
            for (const [table, [comment, columns]] of Object.entries(BASE)) {
                await connection.run(`CREATE TABLE IF NOT EXISTS ${table} (${columns.map(([name, type]) => `${name} ${type}`).join(', ')})`);
                await connection.run(`COMMENT ON TABLE ${table} IS ${quote(comment)}`);
                for (const [name, , text] of columns)
                    if (text !== '')
                        await connection.run(`COMMENT ON COLUMN ${table}.${name} IS ${quote(text)}`);
            }
            if (stale.length > 0) {
                const ids = stale.map(session => quote(session.session_id)).join(', ');
                for (const table of Object.keys(BASE))
                    await connection.run(`DELETE FROM ${table} WHERE session_id IN (${ids})`);
            }
            for (const [table, rows] of Object.entries(tables)) {
                if (rows.length === 0)
                    continue;
                const file = join(staging, `${table}.ndjson`);
                writeFileSync(file, rows.map(row => JSON.stringify(row, wellFormed)).join('\n') + '\n');
                const columns = BASE[table][1].map(([name, type]) => `${name}: ${quote(type)}`).join(', ');
                await connection.run(`INSERT INTO ${table} SELECT * FROM read_json(${quote(file)}, format = 'newline_delimited', columns = {${columns}})`);
            }
            for (const [table, [comment, sql]] of Object.entries(DERIVED)) {
                await connection.run(`CREATE OR REPLACE TABLE ${table} AS ${sql}`);
                await connection.run(`COMMENT ON TABLE ${table} IS ${quote(comment)}`);
            }
            await connection.run('COMMIT');
        }
        catch (error) {
            await connection.run('ROLLBACK');
            throw error;
        }
        const total = Number((await connection.runAndReadAll('SELECT count(*) AS n FROM sessions')).getRowObjectsJS()[0].n);
        return { db: path, sessions: total, loaded: stale.length, kept: unique.length - stale.length };
    }
    finally {
        rmSync(staging, { recursive: true, force: true });
        close();
    }
}

// Nested too: lists, structs, maps and intervals carry bigints and Dates inside.
function plain(value) {
    if (typeof value === 'bigint')
        return Number.isSafeInteger(Number(value)) ? Number(value) : String(value);
    if (value instanceof Date)
        return value.toISOString();
    if (Array.isArray(value))
        return value.map(plain);
    if (typeof value === 'object' && value !== null)
        return Object.fromEntries(Object.entries(value).map(([key, inner]) => [key, plain(inner)]));
    return value;
}

/** DuckDB values → plain JSON: safe BIGINTs as numbers, instants as ISO UTC, JSON columns parsed. */
function plainRows(reader) {
    const types = reader.columnTypes();
    return reader.getRowObjectsJS().map(row => Object.fromEntries(Object.entries(row).map(([key, value], i) =>
        [key, typeof value === 'string' && types[i]?.alias === 'JSON' ? JSON.parse(value) : plain(value)])));
}

/**
 * Queries run on a private copy of the cache, read-only, with file access off
 * and the configuration locked. DuckDB still lets a connection write its own
 * WAL (COPY ... TO '<db>.wal'), so only the copy can be hurt. The copy is taken
 * while holding the cache open read-only, so a running sync (exclusive lock)
 * makes this fail cleanly instead of copying a half-written file.
 */
async function openSandbox(path) {
    if (!existsSync(path))
        throw new Error(`no cache at ${path}: run \`app-telemetry sync\` first (same source flags)`);
    const dir = mkdtempSync(join(tmpdir(), 'app-telemetry-query-'));
    try {
        const copy = join(dir, 'cache.duckdb');
        const held = await connect(path, { access_mode: 'READ_ONLY' });
        try {
            copyFileSync(path, copy);
            if (existsSync(`${path}.wal`))
                copyFileSync(`${path}.wal`, `${copy}.wal`);
        }
        finally {
            held.close();
        }
        const db = await connect(copy, { access_mode: 'READ_ONLY' });
        // A function of an extension not loaded yet (sqlite_scan, httpfs) would
        // otherwise download and load it: a network fetch and new code from a query.
        await db.connection.run('SET autoinstall_known_extensions = false');
        await db.connection.run('SET autoload_known_extensions = false');
        await db.connection.run('SET enable_external_access = false');
        await db.connection.run('SET lock_configuration = true');
        return {
            connection: db.connection,
            close() {
                db.close();
                rmSync(dir, { recursive: true, force: true });
            },
        };
    }
    catch (error) {
        rmSync(dir, { recursive: true, force: true });
        throw error;
    }
}

const QUERY_TYPES = new Set([StatementType.SELECT, StatementType.EXPLAIN]);
// Functions refused wherever they appear in a query. The logging table functions
// change the instance and bypass lock_configuration (and in DuckDB 1.4.5 a denied
// file sink can abort the process instead of raising); query() and query_table()
// run SQL or name tables given as text, which no check of the query's own text sees.
// Matched on DuckDB's own parse tree (json_serialize_sql), never on the text: a
// quoted, upper-cased or commented name ("enable_logging" (...)) is the same node.
const REFUSED_FUNCTIONS = new Map([
    ['enable_logging', 'logging functions are not allowed'],
    ['disable_logging', 'logging functions are not allowed'],
    ['truncate_duckdb_logs', 'logging functions are not allowed'],
    ['query', 'query() and query_table() run SQL given as text: write the query itself'],
    ['query_table', 'query() and query_table() run SQL given as text: write the query itself'],
]);
// Only whitespace and comments may come before EXPLAIN [ANALYZE]; no string can,
// so cutting them off cannot change what follows.
const EXPLAIN_HEAD = /^(?:\s+|--[^\n]*(?:\n|$)|\/\*[\s\S]*?\*\/)*EXPLAIN\s+(?:ANALYZE\s+)?/i;

async function parseTree(connection, sql) {
    const statement = await connection.prepare('SELECT json_serialize_sql($1::VARCHAR) AS tree');
    statement.bindVarchar(1, sql);
    return JSON.parse((await statement.runAndReadAll()).getRowObjectsJS()[0].tree);
}

function functionNames(node, found = new Set()) {
    if (Array.isArray(node))
        node.forEach(item => functionNames(item, found));
    else if (typeof node === 'object' && node !== null)
        for (const [key, value] of Object.entries(node)) {
            if (key === 'function_name' && typeof value === 'string')
                found.add(value.toLowerCase());
            else
                functionNames(value, found);
        }
    return found;
}

/**
 * Refuse a query whose parse tree calls a REFUSED_FUNCTIONS entry. Only SELECTs
 * serialize, so a lone EXPLAIN [ANALYZE] is checked on what it explains (ANALYZE
 * runs it); anything that still does not serialize is refused: what cannot be
 * read is not run. Called after the statement types are checked and before
 * anything runs (binding a statement has no effect; running it does).
 */
async function checkFunctions(connection, sql, count) {
    let tree = await parseTree(connection, sql);
    if (tree.error) {
        const head = count === 1 ? EXPLAIN_HEAD.exec(sql) : null;
        tree = head === null ? tree : await parseTree(connection, sql.slice(head[0].length));
        if (tree.error)
            throw new Error(`sql: this query cannot be checked (${tree.error_message}); EXPLAIN runs alone, before a plain query`);
    }
    for (const name of functionNames(tree.statements))
        if (REFUSED_FUNCTIONS.has(name))
            throw new Error(`sql: ${REFUSED_FUNCTIONS.get(name)}`);
}

export async function query(path, sql) {
    const { connection, close } = await openSandbox(path);
    try {
        const statements = await connection.extractStatements(sql);
        const prepared = [];
        for (let i = 0; i < statements.count; i++) {
            const statement = await statements.prepare(i);
            if (!QUERY_TYPES.has(statement.statementType))
                throw new Error(`sql: only queries run here (SELECT, WITH, FROM, SHOW, DESCRIBE, SUMMARIZE, EXPLAIN), not ${StatementType[statement.statementType]}`);
            prepared.push(statement);
        }
        await checkFunctions(connection, sql, statements.count);
        let rows = [];
        for (const statement of prepared)
            rows = plainRows(await statement.runAndReadAll());
        return rows;
    }
    finally {
        close();
    }
}

/** Every table of the cache: comment, row count, columns with type and comment. */
export async function describeCache(path) {
    const { connection, close } = await openSandbox(path);
    try {
        const tables = plainRows(await connection.runAndReadAll(
            "SELECT table_name, comment FROM duckdb_tables() WHERE database_name = current_database() ORDER BY table_name"));
        const columns = plainRows(await connection.runAndReadAll(
            "SELECT table_name, column_name, data_type, comment FROM duckdb_columns() WHERE database_name = current_database() ORDER BY table_name, column_index"));
        const result = [];
        for (const { table_name: table, comment } of tables) {
            const [{ n }] = plainRows(await connection.runAndReadAll(`SELECT count(*) AS n FROM ${table}`));
            result.push({
                table, rows: n, comment,
                columns: columns.filter(c => c.table_name === table)
                    .map(c => ({ name: c.column_name, type: c.data_type, ...(c.comment ? { comment: c.comment } : {}) })),
            });
        }
        return result;
    }
    finally {
        close();
    }
}