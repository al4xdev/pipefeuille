// session.v4.jsonl.zstd → { header, events }.
//
// dsh appends one zstd frame per batch, and node's one-shot and stream
// decoders both stop after the first frame, so frames are located
// structurally and decoded one by one. scanZstdFrames is copied from
// @deepseek-ai/dsh-session-persistence-jsonl 0.2.0-rc.2 (MIT). A copy taken
// while dsh is still appending (docker cp of a live session) can end inside a
// frame: that torn tail is decoded with a flush (no checksum) and a trailing
// partial line is dropped.
import { constants, zstdDecompressSync } from 'node:zlib';

const ZSTD_MAGIC = 4247762216;

export function scanZstdFrames(buffer) {
    const frames = [];
    let offset = 0;
    while (offset < buffer.length) {
        const start = offset;
        if (buffer.length - offset < 4)
            return { frames, tornStart: start };
        if (buffer.readUInt32LE(offset) !== ZSTD_MAGIC)
            throw new Error(`corrupt Zstandard session log: invalid frame magic at byte ${offset}`);
        offset += 4;
        if (offset === buffer.length)
            return { frames, tornStart: start };
        const descriptor = buffer.readUInt8(offset);
        offset += 1;
        if ((descriptor & 24) !== 0)
            throw new Error(`corrupt Zstandard session log: reserved frame-header bit at byte ${offset - 1}`);
        const contentSizeFlag = descriptor >>> 6;
        const singleSegment = (descriptor & 32) !== 0;
        const checksum = (descriptor & 4) !== 0;
        const dictionaryFlag = descriptor & 3;
        const dictionaryBytes = dictionaryFlag === 3 ? 4 : dictionaryFlag;
        const contentSizeBytes = contentSizeFlag === 0 ? (singleSegment ? 1 : 0) : 1 << contentSizeFlag;
        const remainingHeaderBytes = (singleSegment ? 0 : 1) + dictionaryBytes + contentSizeBytes;
        if (buffer.length - offset < remainingHeaderBytes)
            return { frames, tornStart: start };
        offset += remainingHeaderBytes;
        for (;;) {
            if (buffer.length - offset < 3)
                return { frames, tornStart: start };
            const blockHeader = buffer.readUIntLE(offset, 3);
            offset += 3;
            const lastBlock = (blockHeader & 1) !== 0;
            const blockType = (blockHeader >>> 1) & 3;
            const blockSize = blockHeader >>> 3;
            if (blockType === 3)
                throw new Error(`corrupt Zstandard session log: reserved block type at byte ${offset - 3}`);
            const payloadBytes = blockType === 1 ? 1 : blockSize;
            if (buffer.length - offset < payloadBytes)
                return { frames, tornStart: start };
            offset += payloadBytes;
            if (lastBlock)
                break;
        }
        if (checksum) {
            if (buffer.length - offset < 4)
                return { frames, tornStart: start };
            offset += 4;
        }
        frames.push({ start, end: offset });
    }
    return { frames };
}

/** All plaintext of a session log, including what a torn final frame yields. */
export function decompressSessionLog(buffer) {
    const { frames, tornStart } = scanZstdFrames(buffer);
    const parts = frames.map(({ start, end }) => zstdDecompressSync(buffer.subarray(start, end)));
    if (tornStart !== undefined) {
        try {
            parts.push(zstdDecompressSync(buffer.subarray(tornStart), { finishFlush: constants.ZSTD_e_flush }));
        }
        catch {
            // A tail too short to yield anything: the next copy completes it.
        }
    }
    return Buffer.concat(parts).toString('utf8');
}

/**
 * Parse the log: the first line is the session header ({type: 'session', id,
 * cwd, createdAt}), the rest are {type, seq, time, data} events. A line that
 * does not parse is the cut end of a torn frame and is dropped.
 */
export function parseSessionLog(text) {
    let header;
    const events = [];
    for (const line of text.split('\n')) {
        if (line === '')
            continue;
        let record;
        try {
            record = JSON.parse(line);
        }
        catch {
            continue;
        }
        if (header === undefined && record?.type === 'session' && record.seq === undefined)
            header = record;
        else if (typeof record?.type === 'string' && Number.isSafeInteger(record.seq))
            events.push(record);
    }
    return { header, events };
}

export function decodeSession(buffer) {
    return parseSessionLog(decompressSessionLog(buffer));
}

/** The header alone: dsh writes it in the first frame, so the rest stays compressed. */
export function readHeader(buffer) {
    const { frames } = scanZstdFrames(buffer);
    if (frames.length > 0) {
        const { header } = parseSessionLog(zstdDecompressSync(buffer.subarray(frames[0].start, frames[0].end)).toString('utf8'));
        if (header !== undefined)
            return header;
    }
    return decodeSession(buffer).header;
}