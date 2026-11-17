// expandAssistantStream and its validator, copied from @deepseek-ai/dsh-llm
// 0.2.0-rc.2 (MIT, lib/types/assistant-stream.js) so the trajectory fold does
// not pull the whole LLM package. The two @deepseek-ai/dsh-util-values helpers
// it used are replaced below: our input is parsed JSON, so a JSON round trip is
// the same lossless snapshot.

function snapshotJsonValue(value) {
    try {
        const text = JSON.stringify(value);
        return text === undefined ? undefined : JSON.parse(text);
    }
    catch {
        return undefined;
    }
}
function deepFreeze(value) {
    if (typeof value === 'object' && value !== null && !Object.isFrozen(value)) {
        Object.freeze(value);
        for (const member of Object.values(value))
            deepFreeze(member);
    }
    return value;
}
function safeTime(value) {
    if (!Number.isSafeInteger(value))
        throw new TypeError(`Assistant stream time must be a safe integer, got ${String(value)}`);
    return value;
}
function safeIndex(value, label) {
    if (!Number.isSafeInteger(value) || value < 0 || Object.is(value, -0)) {
        throw new TypeError(`${label} index must be a non-negative safe integer`);
    }
    return value;
}
function snapshotChunk(chunk) {
    const snapshot = snapshotJsonValue(chunk);
    if (snapshot === undefined)
        throw new TypeError('Assistant stream chunk must be losslessly JSON-serializable');
    return snapshot;
}
/**
 * Expand compact records into the exact timed chunk sequence.
 * @param stream - compact records from one durable Assistant settlement.
 * @returns detached timed chunks with every original delta boundary preserved.
 * @throws {TypeError} when a record or reconstructed timestamp is invalid.
 */
export function expandAssistantStream(stream) {
    const chunks = [];
    for (const candidate of stream) {
        const record = validateRecord(candidate);
        if (record.type === 'chunk') {
            chunks.push({ time: record.time, chunk: record.chunk });
            continue;
        }
        const members = record.type === 'tool-call-chunks' ? record.args : record.texts;
        let time = record.time0;
        for (let index = 0; index < members.length; index += 1) {
            if (index > 0)
                time += record.dt[index - 1];
            let chunk;
            if (record.type === 'text-chunks') {
                chunk = { type: 'text-delta', index: record.index, text: members[index] };
            }
            else if (record.type === 'reasoning-chunks') {
                chunk = { type: 'reasoning-delta', index: record.index, text: members[index] };
            }
            else {
                chunk = {
                    type: 'tool-call-delta',
                    index: record.index,
                    id: record.id,
                    ...Object.hasOwn(record, 'name') ? { name: record.name } : {},
                    argumentsDelta: members[index],
                };
            }
            chunks.push({ time, chunk });
        }
    }
    return chunks;
}
function validateRecord(value) {
    if (typeof value !== 'object' || value === null || Array.isArray(value)) {
        throw new TypeError('Assistant stream record must be an object');
    }
    const record = value;
    switch (record.type) {
        case 'text-chunks':
        case 'reasoning-chunks': {
            exactKeys(record, ['type', 'time0', 'index', 'dt', 'texts'], record.type);
            const texts = stringArray(record.texts, `${record.type} texts`);
            if (texts.length === 0)
                throw new TypeError(`${record.type} texts must be non-empty`);
            validateRun(record, texts.length, record.type);
            return record;
        }
        case 'tool-call-chunks': {
            const keys = Object.hasOwn(record, 'name')
                ? ['type', 'time0', 'index', 'dt', 'id', 'name', 'args']
                : ['type', 'time0', 'index', 'dt', 'id', 'args'];
            exactKeys(record, keys, record.type);
            const args = stringArray(record.args, 'tool-call-chunks args');
            if (args.length === 0)
                throw new TypeError('tool-call-chunks args must be non-empty');
            if (typeof record.id !== 'string' || record.id.length === 0) {
                throw new TypeError('tool-call-chunks id must be a non-empty string');
            }
            if (record.name !== undefined && (typeof record.name !== 'string' || record.name.length === 0)) {
                throw new TypeError('tool-call-chunks name must be a non-empty string');
            }
            validateRun(record, args.length, record.type);
            return record;
        }
        case 'chunk': {
            exactKeys(record, ['type', 'time', 'chunk'], 'chunk');
            const time = safeTime(record.time);
            if (typeof record.chunk !== 'object'
                || record.chunk === null
                || Array.isArray(record.chunk)) {
                throw new TypeError('Assistant stream raw chunk must be a lossless JSON object');
            }
            let chunk;
            try {
                chunk = snapshotChunk(record.chunk);
            }
            catch (error) {
                throw new TypeError('Assistant stream raw chunk must be a lossless JSON object', { cause: error });
            }
            return deepFreeze({ type: 'chunk', time, chunk });
        }
        default:
            throw new TypeError(`Unsupported Assistant stream record ${JSON.stringify(record.type)}`);
    }
}
function validateRun(record, members, label) {
    safeTime(record.time0);
    safeIndex(record.index, label);
    if (!Array.isArray(record.dt) || record.dt.some(value => !Number.isSafeInteger(value))) {
        throw new TypeError(`${label} dt must contain safe integers`);
    }
    if (record.dt.length !== members - 1) {
        throw new TypeError(`${label} dt length must be one less than its members`);
    }
    let time = record.time0;
    for (const gap of record.dt) {
        time += gap;
        if (!Number.isSafeInteger(time))
            throw new TypeError(`${label} member times must stay safe integers`);
    }
}
function stringArray(value, label) {
    if (!Array.isArray(value) || value.some(member => typeof member !== 'string')) {
        throw new TypeError(`${label} must be a string array`);
    }
    return value;
}
function exactKeys(record, keys, label) {
    if (Object.keys(record).length !== keys.length || !keys.every(key => Object.hasOwn(record, key))) {
        throw new TypeError(`${label} Assistant stream record must contain exactly ${keys.join(', ')}`);
    }
}