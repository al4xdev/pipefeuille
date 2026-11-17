import { test } from 'node:test';
import assert from 'node:assert/strict';
import { PassThrough, Writable } from 'node:stream';
import { stripVTControlCharacters } from 'node:util';
import { jsx as _jsx } from 'react/jsx-runtime';
import React from 'react';
import { render } from 'ink';
import { App } from '../src/tui.js';
import { acceptSuggestion, parseFilterText, SessionsScreen, suggestFilter } from '../src/screens/sessions.js';
import { ONE_TURN, SESSIONS_DIR, TWO_TURNS } from './helpers.js';

// A 140x36 terminal. debug: true makes ink write every frame whole, so the last write is the screen.
function terminal() {
    const stdin = Object.assign(new PassThrough(), { isTTY: true, setRawMode() { }, ref() { }, unref() { } });
    let frame = '';
    const stdout = Object.assign(new Writable({ write(chunk, _encoding, done) { frame = chunk.toString(); done(); } }),
        { columns: 140, rows: 36, isTTY: true });
    return {
        stdin, stdout,
        screen: () => stripVTControlCharacters(frame),
        async until(pattern, ms = 10000) {
            const end = Date.now() + ms;
            while (!pattern.test(this.screen())) {
                if (Date.now() > end)
                    assert.fail(`screen never showed ${pattern}:\n${this.screen()}`);
                await new Promise(resolve => setTimeout(resolve, 20));
            }
        },
        press: keys => stdin.write(keys),
    };
}

function mount(options) {
    const term = terminal();
    const instance = render(_jsx(App, { options }),
        { stdin: term.stdin, stdout: term.stdout, debug: true, patchConsole: false, exitOnCtrlC: false });
    return { term, instance };
}

test('sessions list → Enter → trajectory → q back → q quits', async () => {
    const { term, instance } = mount({ dir: SESSIONS_DIR });
    await term.until(/2\/2 sessions/);
    assert.match(term.screen(), new RegExp(TWO_TURNS.process_id));
    assert.match(term.screen(), /summarizer/);
    // Newest first: the cursor starts on the one-turn session; j moves to the two-turn one.
    term.press('j');
    await new Promise(resolve => setTimeout(resolve, 50));
    term.press('\r');
    await term.until(/Trajectory/);
    assert.match(term.screen(), /2 turns · 14 rows/);
    assert.match(term.screen(), /finalize_summary/);
    term.press('q');
    await term.until(/✦ sessions/);
    term.press('q');
    await instance.waitUntilExit();
});

test('flags seed the filter; / edits it; a bad date shows inline', async () => {
    const { term, instance } = mount({ dir: SESSIONS_DIR, tenant_id: 't2' });
    await term.until(/0\/2 sessions/);
    assert.match(term.screen(), /no session matches the filter/);
    term.press('/');
    await term.until(/Esc cancel/);
    // `/` opens the filter ready for a next word: the trailing space goes first.
    term.press('\x7f\x7f\x7f');
    await term.until(/\/ tenant_id:(\s|$)/m);
    term.press('acme date:2026-13');
    await term.until(/expected YYYY-MM-DD/);
    term.press('\x7f'.repeat(12) + '\r');
    await term.until(/1\/2 sessions/);
    assert.match(term.screen(), /\/ tenant_id:acme/);
    instance.unmount();
    await instance.waitUntilExit();
});

test('filter text: key:value uses the flag names, bare words match any id', () => {
    const row = { tenant_id: 'acme-br', agent_name: 'binary_reverse', process_id: 'b2c7a5b8', session_id: 'session-8b22', started_at: '2026-10-30T15:59:30.454Z' };
    assert.ok(parseFilterText('')(row));
    assert.ok(parseFilterText('tenant_id:acme agent_name:binary')(row));
    assert.ok(parseFilterText('REVERSE b2c7')(row));
    assert.ok(!parseFilterText('process_id:8b22')(row));
    assert.ok(!parseFilterText('date:2026-10-31')(row));
    assert.throws(() => parseFilterText('date:yesterday'), /--date/);
});

test('suggestions: field names, then the values they have, counted after the earlier words', () => {
    const at = '2026-10-30T15:00:00.000Z';
    const sessions = [
        { tenant_id: 'acme', agent_name: 'binary_reverse', process_id: 'p1', session_id: 'session-a1', started_at: at },
        { tenant_id: 'acme', agent_name: 'scorer', process_id: 'p2', session_id: 'session-a2', started_at: at },
        { tenant_id: 'beta', agent_name: 'scorer', process_id: 'p3', session_id: 'session-b1', started_at: '2026-10-29T09:00:00.000Z' },
    ];
    const tokens = text => suggestFilter(text, sessions).map(s => (s.count === undefined ? s.token : `${s.token} ${s.count}`));
    assert.deepEqual(tokens(''), ['tenant_id:', 'agent_name:', 'process_id:', 'session_id:', 'date:']);
    assert.deepEqual(tokens('ag'), ['agent_name:']);
    assert.deepEqual(tokens('tenant_id:'), ['tenant_id:acme 2', 'tenant_id:beta 1']);
    assert.deepEqual(tokens('tenant_id:acme agent_name:'), ['agent_name:binary_reverse 1', 'agent_name:scorer 1']);
    assert.deepEqual(tokens('date:'), ['date:2026-10-30 2', 'date:2026-10-29 1']);
    assert.deepEqual(tokens('session_id:b'), ['session_id:session-b1 1']);
    assert.deepEqual(tokens('scor'), ['agent_name:scorer 2']);
    assert.deepEqual(tokens('tenant_id:acme'), []);
    assert.deepEqual(tokens('tenant_id:acme '), ['agent_name:', 'process_id:', 'session_id:', 'date:']);
    assert.equal(acceptSuggestion('tenant_id:acme ag', 'agent_name:'), 'tenant_id:acme agent_name:');
    assert.equal(acceptSuggestion('tenant_id:acme agent_name:s', 'agent_name:scorer'), 'tenant_id:acme agent_name:scorer ');
});

test('a suggestion counts what its filter leaves: an id is a prefix of longer ids', () => {
    const at = '2026-10-30T15:00:00.000Z';
    const sessions = [
        { tenant_id: 'acme', agent_name: 'scorer', process_id: 'p1', session_id: 'session-a1', started_at: at },
        { tenant_id: 'acme-br', agent_name: 'scorer_v2', process_id: 'p2', session_id: 'session-a2', started_at: at },
    ];
    for (const text of ['tenant_id:', 'agent_name:', 'acme', 'scor'])
        for (const { token, count } of suggestFilter(text, sessions).filter(s => s.count !== undefined))
            assert.equal(count, sessions.filter(parseFilterText(token)).length, `${text} → ${token}`);
    assert.deepEqual(suggestFilter('tenant_id:', sessions).map(s => `${s.token} ${s.count}`), ['tenant_id:acme 2', 'tenant_id:acme-br 1']);
    // A bare word is not a field (`dates` hid date:), and a field in use offers no values.
    assert.ok(suggestFilter('dates ', sessions).some(s => s.token === 'date:'));
    assert.deepEqual(suggestFilter('tenant_id:acme a', sessions).map(s => s.token).filter(t => t.startsWith('tenant_id')), []);
});

test('/ and what follows in one chunk (a paste) is the filter; a lone \\n is Enter', async () => {
    const { term, instance } = mount({ dir: SESSIONS_DIR });
    await term.until(/2\/2 sessions/);
    term.press('/tenant_id:t2\r');
    await term.until(/0\/2 sessions/);
    assert.match(term.screen(), /\/ tenant_id:t2/);
    term.press('/');
    await term.until(/Esc cancel/);
    term.press('\x7f'.repeat(2) + '-');
    await term.until(/\/ tenant_id:t-\s*$/m);
    term.press('\n');
    await term.until(/Enter trajectory/);
    assert.match(term.screen(), /1\/2 sessions/);
    instance.unmount();
    await instance.waitUntilExit();
});

test('↓ before the sessions load does not lose the pick or the cursor', async () => {
    const term = terminal();
    let finish;
    const opened = [];
    function Harness() {
        const [sessions, setSessions] = React.useState([]);
        const [filterText, setFilterText] = React.useState('');
        finish = setSessions;
        return _jsx(SessionsScreen, { label: 'test', sessions, loading: sessions.length === 0, filterText, onFilterText: setFilterText, onOpen: session => opened.push(session.session_id), onRefresh() { }, onQuit() { } });
    }
    const instance = render(_jsx(Harness, {}), { stdin: term.stdin, stdout: term.stdout, debug: true, patchConsole: false, exitOnCtrlC: false });
    term.press('j');
    await new Promise(resolve => setTimeout(resolve, 50));
    term.press('/tenant_id:');
    await term.until(/\/ tenant_id:/);
    term.press('\x1b[B');
    await new Promise(resolve => setTimeout(resolve, 50));
    finish([{ tenant_id: 't1', agent_name: 'a1', process_id: 'p1', session_id: 'session-1', started_at: '2026-10-30T15:00:00.000Z', bytes: 10 }]);
    await term.until(/▸ tenant_id:t1\s+1 session/);
    term.press('\t\r');
    await term.until(/Enter trajectory/);
    // The `j` pressed while loading left the cursor on a real row.
    term.press('\r');
    await new Promise(resolve => setTimeout(resolve, 50));
    assert.deepEqual(opened, ['session-1']);
    instance.unmount();
    await instance.waitUntilExit();
});

test('keys in one batch (fast typing, paste) each see the previous one', async () => {
    const { term, instance } = mount({ dir: SESSIONS_DIR });
    await term.until(/2\/2 sessions/);
    term.press('/\x1b[B\x1b[B\t');
    await term.until(new RegExp(`▸ process_id:${TWO_TURNS.process_id}\\s+1 session`));
    // Plain text with Tab and Enter in it comes from ink as one input.
    term.press('9\t\r');
    await term.until(/Enter trajectory/);
    assert.match(term.screen(), new RegExp(`/ process_id:${ONE_TURN.process_id}\\s*$`, 'm'));
    assert.match(term.screen(), /1\/2 sessions/);
    instance.unmount();
    await instance.waitUntilExit();
});

test('/ then Tab picks a field, Tab picks its value, Enter applies', async () => {
    const { term, instance } = mount({ dir: SESSIONS_DIR });
    await term.until(/2\/2 sessions/);
    term.press('/');
    await term.until(/▸ tenant_id:/);
    term.press('\t');
    await term.until(/▸ tenant_id:acme\s+1 session/);
    term.press('\t');
    // The value is in, and the next suggestion is the next field.
    await term.until(/▸ agent_name:/);
    assert.match(term.screen(), /\/ tenant_id:acme\s*$/m);
    term.press('\r');
    await term.until(/Enter trajectory/);
    assert.match(term.screen(), /1\/2 sessions/);
    assert.match(term.screen(), /\/ tenant_id:acme/);
    instance.unmount();
    await instance.waitUntilExit();
});