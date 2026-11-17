import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { existsSync, mkdtempSync, readdirSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { describeCache, query, syncCache } from '../src/db.js';
import { dirSource, loadSession } from '../src/sources.js';
import { ONE_TURN, SESSIONS_DIR, TWO_TURNS } from './helpers.js';
import { refusals } from './refusals.js';

let scratch;
let db;
before(() => {
    scratch = mkdtempSync(join(tmpdir(), 'app-telemetry-test-'));
    db = join(scratch, 'cache.duckdb');
});
after(() => rmSync(scratch, { recursive: true, force: true }));

async function syncDir(root, mutate = sessions => sessions) {
    const source = dirSource(root);
    return syncCache(db, mutate(await source.list()), session => loadSession(source, session));
}

// The tests share one cache and run in order: each builds on the previous sync.
test('a filtered sync loads its sessions, a wider one adds the rest, a repeat loads nothing', async () => {
    assert.deepEqual(await syncDir(SESSIONS_DIR, s => s.filter(x => x.tenant_id === 'acme')), { db, sessions: 1, loaded: 1, kept: 0 });
    assert.deepEqual(await syncDir(SESSIONS_DIR), { db, sessions: 2, loaded: 1, kept: 1 });
    assert.deepEqual(await syncDir(SESSIONS_DIR), { db, sessions: 2, loaded: 0, kept: 2 });
    // A filtered sync never drops the others.
    assert.deepEqual(await syncDir(SESSIONS_DIR, s => s.filter(x => x.tenant_id === 'acme')), { db, sessions: 2, loaded: 0, kept: 1 });
});

test('a size change re-decodes, replacing the rows', async () => {
    const grown = await syncDir(SESSIONS_DIR, sessions => sessions.map(s => ({ ...s, bytes: s.bytes + 1 })));
    assert.deepEqual(grown, { db, sessions: 2, loaded: 2, kept: 0 });
    const [{ n }] = await query(db, `SELECT count(*) AS n FROM events WHERE session_id = '${TWO_TURNS.session_id}'`);
    assert.equal(n, 33, 'the re-sync replaced the events instead of appending a copy');
});

test('features are the fold totals the TUI shows', async () => {
    const [two] = await query(db, `SELECT source, tenant_id, agent_name, process_id, started_at, turns, rows, calls, errors, input_tokens, output_tokens, cache_read_tokens FROM sessions WHERE session_id = '${TWO_TURNS.session_id}'`);
    assert.deepEqual(two, {
        source: 'dir', tenant_id: 't-1_x', agent_name: 'summarizer', process_id: TWO_TURNS.process_id, started_at: TWO_TURNS.started_at,
        turns: 2, rows: 14, calls: 2, errors: 0, input_tokens: 300, output_tokens: 30, cache_read_tokens: 15,
    });
    const turns = await query(db, `SELECT label, total_ms FROM hotspots WHERE session_id = '${TWO_TURNS.session_id}' AND section = 'turns' ORDER BY label`);
    assert.deepEqual(turns, [{ label: 'turn 1', total_ms: 74 }, { label: 'turn 2', total_ms: 36 }]);
    const [one] = await query(db, `SELECT tenant_id, turns, input_tokens FROM sessions WHERE session_id = '${ONE_TURN.session_id}'`);
    assert.deepEqual(one, { tenant_id: 'acme', turns: 1, input_tokens: 200 });
});

test('derived tables agree with the base tables', async () => {
    const [calls] = await query(db, "SELECT count(*) AS n, count(result_seq) AS answered, bool_or(is_error) AS failed FROM tool_calls");
    const [rows] = await query(db, "SELECT sum(members) AS n FROM rows WHERE kind = 'tool'");
    assert.equal(calls.n, rows.n);
    assert.equal(calls.answered, calls.n);
    assert.equal(calls.failed, false);
    const names = await query(db, `SELECT name FROM tool_calls WHERE session_id = '${TWO_TURNS.session_id}' ORDER BY seq`);
    assert.deepEqual(names.map(r => r.name), ['read', 'finalize_summary']);
    const turns = await query(db, `SELECT turn, duration_ms, outcome FROM turns WHERE session_id = '${TWO_TURNS.session_id}' ORDER BY turn`);
    assert.deepEqual(turns, [{ turn: 1, duration_ms: 74, outcome: 'completed' }, { turn: 2, duration_ms: 36, outcome: 'completed' }]);
    const [model] = await query(db, `SELECT count(*) AS n, sum(input_tokens) AS input FROM model_calls WHERE session_id = '${TWO_TURNS.session_id}'`);
    assert.deepEqual(model, { n: 3, input: 300 });
});

test('rows come out as plain JSON: numbers, ISO UTC, parsed JSON columns', async () => {
    const [row] = await query(db, "SELECT seq, time, data FROM events WHERE type = 'turn/start' ORDER BY time LIMIT 1");
    assert.equal(typeof row.seq, 'number');
    assert.match(row.time, /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$/);
    assert.equal(typeof row.data, 'object');
    assert.equal(row.data.turn, 1);
});

const sha = path => createHash('sha256').update(readFileSync(path)).digest('hex');

for (const what of Object.keys(refusals(''))) {
    test(`queries refuse ${what}; the cache stays byte for byte and nothing lands on disk`, async () => {
        const before = sha(db);
        const dir = mkdtempSync(join(scratch, 'refuse-'));
        for (const [sql, refused] of refusals(dir)[what])
            await assert.rejects(query(db, sql), refused, sql);
        assert.equal(sha(db), before);
        // DuckDB lets a connection write its own WAL: queries run on a private copy, so the cache's never appears.
        assert.equal(existsSync(`${db}.wal`), false);
        assert.deepEqual(readdirSync(dir), []);
    });
}

test('read-only statements still run: SELECT, FROM-first, SHOW, DESCRIBE, SUMMARIZE, EXPLAIN', async () => {
    for (const sql of ['SELECT 1 AS one', 'FROM sessions SELECT count(*) AS n', 'SHOW TABLES', 'DESCRIBE sessions', 'SUMMARIZE turns', 'EXPLAIN SELECT * FROM events',
        '/* why */ EXPLAIN ANALYZE SELECT count(*) FROM events', 'SELECT 1 AS a; SELECT 2 AS b', "SELECT json_extract_string(data, '$.turn') AS t FROM events"])
        assert.ok((await query(db, sql)).length > 0, sql);
    // The sandbox's own settings read back as set.
    const [settings] = await query(db, "SELECT current_setting('enable_external_access') AS files, current_setting('lock_configuration') AS locked, current_setting('autoload_known_extensions') AS autoload");
    assert.deepEqual(settings, { files: false, locked: true, autoload: false });
});

test('nested values come out as plain JSON too', async () => {
    const [row] = await query(db, `SELECT list(seq::BIGINT ORDER BY seq) AS seqs, max(time) - min(time) AS span, {'n': count(*)::BIGINT} AS s FROM events WHERE session_id = '${TWO_TURNS.session_id}'`);
    assert.equal(typeof row.seqs[0], 'number');
    assert.equal(typeof row.s.n, 'number');
    assert.doesNotThrow(() => JSON.stringify(row));
});

test('schema describes every table, with comments', async () => {
    const tables = await describeCache(db);
    assert.deepEqual(tables.map(t => t.table),
        ['events', 'hotspots', 'model_calls', 'rows', 'sessions', 'tool_calls', 'turns']);
    for (const table of tables)
        assert.ok(table.comment, `${table.table} has no comment`);
    const sessions = tables.find(t => t.table === 'sessions');
    assert.equal(sessions.rows, 2);
    assert.equal(sessions.columns.length, 27);
    assert.ok(sessions.columns.find(c => c.name === 'agent_name').comment.includes('agents/'));
});

test('a cache with an older column layout is rebuilt on sync', async () => {
    const old = join(scratch, 'old.duckdb');
    const { DuckDBInstance } = await import('@duckdb/node-api');
    const instance = await DuckDBInstance.create(old);
    const connection = await instance.connect();
    await connection.run("CREATE TABLE sessions (session_id VARCHAR, bytes BIGINT); INSERT INTO sessions VALUES ('session-gone', 1)");
    connection.closeSync();
    instance.closeSync();
    const source = dirSource(SESSIONS_DIR);
    const result = await syncCache(old, await source.list(), session => loadSession(source, session));
    assert.deepEqual(result, { db: old, sessions: 2, loaded: 2, kept: 0 });
    assert.equal((await describeCache(old)).find(t => t.table === 'sessions').columns.length, 27);
});

test('no cache: the error says to sync', async () => {
    await assert.rejects(query(join(scratch, 'missing.duckdb'), 'SELECT 1'), /run `app-telemetry sync` first/);
});

// A made-up session in the real event shapes: turn 1 calls `read` 3 times in a
// row (a burst on screen, the 2nd fails), turn 2 reuses call id read#0.
function syntheticSession() {
    const id = 'session-00000000-0000-4000-8000-000000000001';
    const events = [];
    let seq = 0;
    const at = ms => Date.parse('2026-10-30T12:00:00.000Z') + ms;
    const push = (type, ms, data) => events.push({ type, seq: ++seq, time: at(ms), data });
    // error: the call failed to run (data.error); refused: the tool ran and answered
    // with an error (only message.isError), as dsh writes a fence or SQL refusal.
    const call = (turn, callId, ms, took, error, refused = false) => {
        push('tool/call', ms, { turn, step: 1, callId, name: 'read', arguments: '{}' });
        push('tool/result', ms + took, {
            turn, step: 1, ...(error ? { error: { code: 'E_READ', message: 'no' } } : {}),
            message: { role: 'tool', source: { kind: 'tool', callId }, toolCallId: callId, content: [{ type: 'text', text: `out \ud800 ${callId}` }], isError: error || refused },
        });
    };
    push('turn/start', 0, { turn: 1 });
    call(1, 'read#0', 10, 10, false);
    call(1, 'read#1', 30, 20, true);
    call(1, 'read#2', 60, 30, false);
    push('turn/end', 100, { turn: 1, reason: { kind: 'completed' } });
    push('turn/start', 200, { turn: 2 });
    call(2, 'read#0', 210, 70, false);
    call(2, 'read#1', 285, 5, false, true);
    push('turn/end', 300, { turn: 2, reason: { kind: 'completed' } });
    const descriptor = {
        session_id: id, source: 'synthetic', tenant_id: 't', agent_name: 'a', process_id: 'p',
        started_at: new Date(at(0)).toISOString(), updated_at: new Date(at(300)).toISOString(), bytes: 1,
    };
    return { descriptor, session: { ...descriptor, header: { type: 'session', version: 4, id, cwd: '/tmp' }, events } };
}

test('tool calls pair like the fold; a burst row stands for its members', async () => {
    const path = join(scratch, 'synthetic.duckdb');
    const { descriptor, session } = syntheticSession();
    // Listed twice: still one session (and a lone surrogate in the output does not break read_json).
    assert.deepEqual(await syncCache(path, [descriptor, descriptor], async () => session),
        { db: path, sessions: 1, loaded: 1, kept: 0 });
    const calls = await query(path, 'SELECT seq, call_id, result_seq, duration_ms, is_error, tool_is_error, error_code FROM tool_calls ORDER BY seq');
    assert.deepEqual(calls.map(c => [c.call_id, c.duration_ms, c.is_error, c.tool_is_error]),
        [['read#0', 10, false, false], ['read#1', 20, true, true], ['read#2', 30, false, false], ['read#0', 70, false, false], ['read#1', 5, false, true]]);
    assert.equal(calls[1].error_code, 'E_READ');
    const [{ errors }] = await query(path, 'SELECT errors FROM sessions');
    assert.equal(errors, calls.filter(c => c.is_error || c.tool_is_error).length);
    const tools = await query(path, "SELECT members, status, duration_ms FROM rows WHERE kind = 'tool' ORDER BY idx");
    assert.deepEqual(tools, [{ members: 3, status: 'error', duration_ms: 60 }, { members: 1, status: 'ok', duration_ms: 70 }, { members: 1, status: 'error', duration_ms: 5 }]);
    const [{ n }] = await query(path, "SELECT sum(members) AS n FROM rows WHERE kind = 'tool'");
    assert.equal(n, calls.length);
});
