import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseSessionPath, workspaceOf } from '../src/paths.js';
import { makeFilter, parseDate } from '../src/filters.js';

const U = '3b7bfa85-deab-4a77-87c8-e2166c4e41fc';
const S = 'session-c15316e8-d738-4c2b-88c8-faabffb250e0';
const at = folder => parseSessionPath(`home/node/.dsh/sessions/${folder}/${S}/session.v4.jsonl.zstd`);

test('tenant with - and _, agent, process, session', () => {
    assert.deepEqual(at(`--tmp-app-work-t-1_x-summarizer-${U}--`),
        { tenant_id: 't-1_x', agent_name: 'summarizer', process_id: U, session_id: S });
    // The agent is the last segment before the uuid: a tenant may hold '-', an agent never does.
    assert.deepEqual(at(`--tmp-app-work-a-b-c_d-${U}--`),
        { tenant_id: 'a-b', agent_name: 'c_d', process_id: U, session_id: S });
});

test('anything else is not a session', () => {
    assert.equal(parseSessionPath('sessions/_probe.txt'), undefined);
    assert.equal(parseSessionPath(`--tmp-app-work-t1-a-${U}--/${S}/session.lock`), undefined);
    // A dsh run outside app-agent (docker.sh run, a capture) has another cwd.
    assert.equal(at('--tmp-context-summarizer--'), undefined);
    // No agent segment, an agent with a leading '_', a character dsh would have escaped.
    assert.equal(at(`--tmp-app-work-t1-${U}--`), undefined);
    assert.equal(at(`--tmp-app-work-t1-_shared-${U}--`), undefined);
    assert.equal(at(`--tmp-app-work-t1~00e9-a-${U}--`), undefined);
    // A numbered chunk folder is not a session file.
    assert.equal(parseSessionPath(`--tmp-app-work-t1-a-${U}--/${S}/session.v4.jsonl.zstd/000001`), undefined);
});

test('header cwd: the unambiguous identity', () => {
    assert.deepEqual(workspaceOf(`/tmp/app-work/acme-br/summarizer/${U}`), { tenant_id: 'acme-br', agent_name: 'summarizer', process_id: U });
    assert.deepEqual(workspaceOf(`/tmp/app-work/acme/br/${U}/`), { tenant_id: 'acme', agent_name: 'br', process_id: U });
    assert.equal(workspaceOf(`/tmp/app-work/acme/${U}`), undefined);
    assert.equal(workspaceOf('/home/x/project'), undefined);
    assert.equal(workspaceOf(undefined), undefined);
});

test('date: day, open ranges, bad input', () => {
    assert.deepEqual(parseDate('2026-10-30'), { from: '2026-10-30', to: '2026-10-30' });
    assert.deepEqual(parseDate('2026-10-01..'), { from: '2026-10-01', to: undefined });
    assert.deepEqual(parseDate('..2026-10-01'), { from: undefined, to: '2026-10-01' });
    assert.throws(() => parseDate('2026-13'), /--date/);
    for (const bad of ['..', '2026-10-01..2026-10-02..2026-10-03', '2026-02-30', '2026-13-01', '2026-10-01..x'])
        assert.throws(() => parseDate(bad), /--date/, bad);
});

test('filters: prefix match, session- optional', () => {
    const row = { tenant_id: 't1', agent_name: 'summarizer', process_id: U, session_id: S, started_at: '2026-10-30T14:44:13.000Z' };
    assert.ok(makeFilter({ process_id: '3b7b' })(row));
    assert.ok(makeFilter({ session_id: 'c153' })(row));
    assert.ok(makeFilter({ session_id: 'session-c153' })(row));
    assert.ok(makeFilter({ agent_name: 'summ' })(row));
    assert.ok(makeFilter({ date: '2026-10-30' })(row));
    assert.ok(!makeFilter({ date: '2026-10-31..' })(row));
    assert.ok(!makeFilter({ agent_name: 'scorer' })(row));
    assert.ok(!makeFilter({ tenant_id: 't2' })(row));
});
