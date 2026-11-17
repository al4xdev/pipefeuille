// --process_id / --tenant_id / --agent_name / --session_id: exact or prefix. A
// session_id may be given without its `session-` folder prefix. --date:
// YYYY-MM-DD or FROM..TO (either side open), compared on started_at in UTC.
const DAY = /^\d{4}-\d{2}-\d{2}$/;
// A real calendar day: 2026-02-30 and 2026-13-01 are typos, not empty ranges.
const isDay = side => {
    const time = Date.parse(`${side}T00:00:00Z`);
    return DAY.test(side) && Number.isFinite(time) && new Date(time).toISOString().startsWith(side);
};

export function parseDate(value) {
    if (value === undefined || value === '')
        return undefined;
    const parts = value.includes('..') ? value.split('..') : [value, value];
    const [from, to] = parts;
    if (parts.length !== 2 || (from === '' && to === '') || [from, to].some(side => side !== '' && !isDay(side)))
        throw new Error(`--date: expected YYYY-MM-DD or FROM..TO, got ${value}`);
    return { from: from || undefined, to: to || undefined };
}

export function makeFilter({ process_id, tenant_id, agent_name, session_id, date } = {}) {
    const range = parseDate(date);
    const sessionNeedle = session_id === undefined || session_id === '' || session_id.startsWith('session-')
        ? session_id
        : `session-${session_id}`;
    const prefix = (value, needle) => needle === undefined || needle === '' || (value ?? '').startsWith(needle);
    return session => {
        if (!prefix(session.process_id, process_id))
            return false;
        if (!prefix(session.tenant_id, tenant_id))
            return false;
        if (!prefix(session.agent_name, agent_name))
            return false;
        if (!prefix(session.session_id, sessionNeedle))
            return false;
        if (range !== undefined) {
            const day = session.started_at.slice(0, 10);
            if (range.from !== undefined && day < range.from)
                return false;
            if (range.to !== undefined && day > range.to)
                return false;
        }
        return true;
    };
}

export const FILTER_KEYS = ['process_id', 'tenant_id', 'agent_name', 'session_id', 'date'];