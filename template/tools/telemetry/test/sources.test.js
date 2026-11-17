import { test, after } from 'node:test';
import assert from 'node:assert/strict';
import { cpSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { zstdCompressSync } from 'node:zlib';
import { decompressSessionLog, readHeader } from '../src/decode.js';
import { dirSource, loadSession } from '../src/sources.js';
import { aggregate, buildTrajectory } from '../src/vendor/dsh-adapter/trajectory/index.js';
import { ONE_TURN, SESSIONS_DIR, TWO_TURNS } from './helpers.js';

const pick = ({ tenant_id, agent_name, process_id, session_id, started_at }) => ({ tenant_id, agent_name, process_id, session_id, started_at });
const scratch = mkdtempSync(join(tmpdir(), 'app-telemetry-sources-'));
after(() => rmSync(scratch, { recursive: true, force: true }));

test('dir of session files: ids from the path, start from the header, newest first, lock file ignored', async () => {
    const sessions = await dirSource(SESSIONS_DIR).list();
    const { file, ...two } = TWO_TURNS;
    assert.deepEqual(sessions.map(pick), [ONE_TURN, two]);
    assert.deepEqual(sessions.map(s => s.source), ['dir', 'dir']);
    assert.equal(sessions[1].file, TWO_TURNS.file);
    assert.equal(sessions[1].bytes, readFileSync(TWO_TURNS.file).length);
});

test('a corrupt file does not hide the other sessions', async () => {
    const root = join(scratch, 'corrupt');
    cpSync(SESSIONS_DIR, root, { recursive: true });
    const bad = join(root, '--tmp-app-work-t1-a-00000000-0000-4000-8000-000000000000--', 'session-00000000-0000-4000-8000-000000000000');
    mkdirSync(bad, { recursive: true });
    writeFileSync(join(bad, 'session.v4.jsonl.zstd'), 'not zstd');
    const sessions = await dirSource(root).list();
    assert.equal(sessions.length, 3);
    assert.ok(sessions.some(s => s.started_at === TWO_TURNS.started_at));
    const broken = sessions.find(s => s.tenant_id === 't1');
    await assert.rejects(loadSession(dirSource(root), broken), /invalid frame magic/);
});

test('readHeader decodes the first frame only', () => {
    const header = readHeader(readFileSync(TWO_TURNS.file));
    assert.equal(header.type, 'session');
    assert.equal(header.createdAt, Date.parse(TWO_TURNS.started_at));
});

test('the header cwd wins over the folder name for the same process', async () => {
    // A folder name a tenant with '-' could be read two ways from; the header says which.
    const text = decompressSessionLog(readFileSync(TWO_TURNS.file))
        .replace(/"cwd":"\/tmp\/([a-z0-9]+)-work\/t-1_x\/summarizer\//, '"cwd":"/tmp/$1-work/t-1_x-summarizer/summarizer/');
    const source = { ...dirSource(scratch), load: async () => zstdCompressSync(text) };
    const listed = { ...TWO_TURNS, tenant_id: 't-1_x', agent_name: 'summarizer' };
    const loaded = await loadSession(source, listed);
    // Only when the header names a workspace of this tool's prefix; a renamed copy keeps the folder's ids.
    if (/"cwd":"\/tmp\/app-work\//.test(text))
        assert.deepEqual([loaded.tenant_id, loaded.agent_name], ['t-1_x-summarizer', 'summarizer']);
    else
        assert.deepEqual([loaded.tenant_id, loaded.agent_name], ['t-1_x', 'summarizer']);
    // A header naming another process never overrides the folder.
    const other = await loadSession(source, { ...listed, process_id: '00000000-0000-4000-8000-000000000000' });
    assert.deepEqual([other.tenant_id, other.agent_name], ['t-1_x', 'summarizer']);
});

test('the fold reads dsh-llm 0.2 token names (vendored readTokens edit)', async () => {
    const source = dirSource(SESSIONS_DIR);
    const session = (await source.list()).find(s => s.session_id === TWO_TURNS.session_id);
    const { totals, tools, turns } = aggregate(buildTrajectory((await loadSession(source, session)).events), 'duration');
    assert.equal(totals.turns, 2);
    assert.equal(totals.calls, 2);
    assert.deepEqual(totals.tokens, { input: 300, output: 30, think: 0, cacheRead: 15, cacheWrite: 0 });
    assert.deepEqual(tools.map(t => t.label).sort(), ['finalize_summary', 'read']);
    assert.deepEqual(turns.map(t => [t.label, t.totalMs]), [['turn 1', 74], ['turn 2', 36]]);
});
