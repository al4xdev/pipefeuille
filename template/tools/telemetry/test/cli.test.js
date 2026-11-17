import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { mkdtempSync, readdirSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { cachePath, parseCli, UsageError } from '../src/cli.js';
import { filterTextOf } from '../src/tui.js';
import { ONE_TURN, SESSIONS_DIR, TWO_TURNS } from './helpers.js';

const BIN = fileURLToPath(new URL('../bin/app-telemetry.js', import.meta.url));
const SRC = fileURLToPath(new URL('../src/', import.meta.url));

// Not a TTY on stdin/stdout, as an agent runs it.
function run(...args) {
    return new Promise(resolve => {
        execFile(process.execPath, [BIN, ...args], { timeout: 60000 }, (error, stdout, stderr) =>
            resolve({ code: error ? error.code : 0, stdout, stderr, lines: stdout.split('\n').filter(Boolean).map(line => JSON.parse(line)) }));
    });
}

let scratch;
let db;
before(() => {
    scratch = mkdtempSync(join(tmpdir(), 'app-telemetry-cli-'));
    db = join(scratch, 'cli.duckdb');
});
after(() => rmSync(scratch, { recursive: true, force: true }));

test('piped with no command: sessions as JSON lines, newest first', async () => {
    const { code, lines } = await run('--dir', SESSIONS_DIR);
    assert.equal(code, 0);
    assert.deepEqual(lines.map(l => l.session_id), [ONE_TURN.session_id, TWO_TURNS.session_id]);
    assert.deepEqual(Object.keys(lines[1]).sort(),
        ['agent_name', 'bytes', 'process_id', 'session_id', 'source', 'started_at', 'tenant_id', 'updated_at']);
    assert.equal(lines[1].tenant_id, 't-1_x');
});

test('filters by the code names', async () => {
    assert.equal((await run('--dir', SESSIONS_DIR, '--agent_name', 'summ', 'sessions')).lines.length, 2);
    assert.equal((await run('--dir', SESSIONS_DIR, '--tenant_id', 't-1', 'sessions')).lines.length, 1);
    assert.equal((await run('--dir', SESSIONS_DIR, '--tenant_id', 'nobody', 'sessions')).lines.length, 0);
    assert.equal((await run('--dir', SESSIONS_DIR, '--date', '2026-11-17', 'sessions')).lines.length, 2);
    assert.equal((await run('--dir', SESSIONS_DIR, '--date', '..2026-11-16', 'sessions')).lines.length, 0);
});

test('trajectory: the fold by session prefix', async () => {
    const { code, lines: [out] } = await run('--dir', SESSIONS_DIR, 'trajectory', 'c153');
    assert.equal(code, 0);
    assert.equal(out.session.session_id, TWO_TURNS.session_id);
    assert.equal(out.totals.turns, 2);
    assert.equal(out.totals.tokens.input, 300);
    assert.equal(out.nodes.length, 14);
    assert.deepEqual(out.hotspots.tools.map(t => t.label).sort(), ['finalize_summary', 'read']);
    const { lines: [detailed] } = await run('--dir', SESSIONS_DIR, 'trajectory', 'c153', '--detail');
    assert.ok(detailed.nodes.every(node => 'inspect' in node));
});

test('trajectory: unknown or ambiguous id is an error', async () => {
    const missing = await run('--dir', SESSIONS_DIR, 'trajectory', 'ffff');
    assert.equal(missing.code, 1);
    assert.match(missing.stderr, /no session ffff/);
    const both = await run('--dir', SESSIONS_DIR, 'trajectory', 'session-');
    assert.equal(both.code, 1);
    assert.match(both.stderr, /matches 2 sessions/);
});

test('sql --sync, then sql and schema offline', async () => {
    const synced = await run('--dir', SESSIONS_DIR, '--db', db, 'sql', '--sync', 'SELECT tenant_id, agent_name, turns FROM sessions ORDER BY tenant_id');
    assert.equal(synced.code, 0, synced.stderr);
    assert.deepEqual(synced.lines, [{ tenant_id: 'acme', agent_name: 'summarizer', turns: 1 }, { tenant_id: 't-1_x', agent_name: 'summarizer', turns: 2 }]);
    // No source flag: the cache alone answers.
    const offline = await run('--db', db, 'sql', 'SELECT count(*) AS n FROM tool_calls');
    assert.deepEqual(offline.lines, [{ n: 4 }]);
    const schema = await run('--db', db, 'schema');
    assert.equal(schema.lines.length, 7);
});

test('sql refuses a write with exit 1 and the reason', async () => {
    const { code, stderr, lines } = await run('--db', db, 'sql', 'DELETE FROM events');
    assert.equal(code, 1);
    assert.deepEqual(lines, []);
    assert.match(stderr, /only queries run here.*not DELETE/);
});

test('sync prints what it did', async () => {
    const { lines } = await run('--dir', SESSIONS_DIR, '--db', db, 'sync');
    assert.deepEqual(lines, [{ db, sessions: 2, loaded: 0, kept: 2 }]);
});

test('usage errors exit 2 with the usage text', async () => {
    // --env and the cloud source are gone: an unknown flag, like any other.
    for (const args of [['--local', '--dir', '.'], ['--env', 'dev'], ['frobnicate'], ['sql'], ['--nope'], ['--date', 'yesterday', 'sessions'], ['--json']]) {
        const { code, stderr } = await run(...args);
        assert.equal(code, 2, args.join(' '));
        assert.match(stderr, /usage:/i, args.join(' '));
    }
});

test('--local (the default source) needs docker: a clear error, exit 1', async () => {
    const { code, stderr } = await new Promise(resolve => execFile(process.execPath, [BIN, 'sessions'],
        { timeout: 60000, env: { ...process.env, PATH: '/nonexistent' } }, (error, stdout, err) => resolve({ code: error ? error.code : 0, stderr: err })));
    assert.equal(code, 1);
    assert.match(stderr, /docker not found on PATH/);
});

test('a missing cache exits 1 and says to sync', async () => {
    const { code, stderr } = await run('--db', join(scratch, 'none.duckdb'), 'schema');
    assert.equal(code, 1);
    assert.match(stderr, /run `app-telemetry sync` first/);
});

test('cache path: one per source, from the flags only', () => {
    const at = args => cachePath(parseCli(args).options);
    assert.match(at([]), /app-telemetry\/local\.duckdb$/);
    assert.equal(at(['--local']), at([]));
    assert.match(at(['--dir', SESSIONS_DIR]), /app-telemetry\/dir-[0-9a-f]{8}\.duckdb$/);
    assert.equal(at(['--dir', SESSIONS_DIR]), at(['--dir', `${SESSIONS_DIR}/`]));
    assert.notEqual(at(['--dir', SESSIONS_DIR]), at(['--dir', scratch]));
    assert.equal(at(['--db', '/x.duckdb']), '/x.duckdb');
    assert.throws(() => parseCli(['--local', '--dir', '.']), UsageError);
});

test('flags seed the TUI filter line with the same names', () => {
    const { options } = parseCli(['--tenant_id', 't1', '--date', '2026-10-30']);
    assert.equal(filterTextOf(options), 'tenant_id:t1 date:2026-10-30');
});

test('only db.js imports DuckDB, and nothing imports db.js statically', () => {
    const files = readdirSync(SRC, { recursive: true }).filter(f => f.endsWith('.js'));
    for (const file of files) {
        const text = readFileSync(join(SRC, file), 'utf8');
        if (file !== 'db.js')
            assert.doesNotMatch(text, /@duckdb/, file);
        assert.doesNotMatch(text, /^import [^;]*from '\.\/db\.js'/m, file);
    }
});
