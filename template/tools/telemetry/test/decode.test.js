import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { zstdDecompressSync } from 'node:zlib';
import { decodeSession, scanZstdFrames } from '../src/decode.js';
import { TWO_TURNS } from './helpers.js';

const buffer = readFileSync(TWO_TURNS.file);

test('one zstd frame per append: node alone decodes only the first', () => {
    const { frames, tornStart } = scanZstdFrames(buffer);
    assert.equal(frames.length, 10);
    assert.equal(tornStart, undefined);
    assert.equal(frames.at(-1).end, buffer.length);
    assert.equal(zstdDecompressSync(buffer).toString().split('\n').filter(Boolean).length, 1);
});

test('all frames: the header line apart, then seq-ordered events', () => {
    const { header, events } = decodeSession(buffer);
    assert.equal(header.type, 'session');
    assert.equal(header.id, TWO_TURNS.session_id);
    // The workspace app-agent made; the prefix is checked loosely so a renamed project's tests still pass.
    assert.match(header.cwd, new RegExp(`^/tmp/[a-z0-9]+-work/t-1_x/summarizer/${TWO_TURNS.process_id}$`));
    assert.equal(events.length, 33);
    assert.deepEqual(events.map(e => e.seq), [...events.map(e => e.seq)].sort((a, b) => a - b));
});

test('a copy cut inside a frame (a live session) still yields the events before the cut', () => {
    const whole = decodeSession(buffer).events;
    const torn = decodeSession(buffer.subarray(0, buffer.length - 40));
    assert.ok(torn.events.length > 0 && torn.events.length < whole.length);
    assert.deepEqual(torn.events, whole.slice(0, torn.events.length));
});

test('garbage is an error, not an empty session', () => {
    assert.throws(() => decodeSession(Buffer.from('not zstd at all')), /invalid frame magic/);
});
