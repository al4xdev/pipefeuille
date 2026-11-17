// The screen before the trajectory: the sessions of the source, newest first.
// `/` filters with the CLI's own names (tenant_id:t1 date:2026-10-01..), so a
// filter typed here and a --flag mean the same thing; a bare word matches any id.
import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import React from 'react';
import { Box, Text, useInput, useTerminalSize } from '../vendor/ui.js';
import { HintLine } from '../vendor/components/design-system/HintLine.js';
import { Divider } from '../vendor/components/design-system/Divider.js';
import { truncateWidth } from '../vendor/trajectory/format.js';
import { FILTER_KEYS, makeFilter } from '../filters.js';

const ID_FIELDS = ['tenant_id', 'agent_name', 'process_id', 'session_id'];

/** `key:value` tokens → makeFilter options; other words → free-text needles. Throws on a bad date. */
export function parseFilterText(text) {
    const options = {};
    const words = [];
    for (const token of text.trim().split(/\s+/).filter(Boolean)) {
        const cut = token.indexOf(':');
        const key = cut > 0 ? token.slice(0, cut) : '';
        if (FILTER_KEYS.includes(key))
            options[key] = token.slice(cut + 1);
        else
            words.push(token.toLowerCase());
    }
    const keep = makeFilter(options);
    return session => keep(session)
        && words.every(word => ID_FIELDS.some(field => (session[field] ?? '').toLowerCase().includes(word)));
}

const dayOf = session => session.started_at.slice(0, 10);
// Broad to narrow, the order you drill down in.
const FIELD_ORDER = ['tenant_id', 'agent_name', 'process_id', 'session_id', 'date'];

/**
 * Completions for the word being typed (the last one): field names first, then
 * the values that field really has, each with the sessions it would leave.
 * Counted over the sessions the words before it already keep, so every option
 * narrows to something. { token, count? }, most sessions first.
 */
export function suggestFilter(text, sessions, limit = 6) {
    const cut = text.lastIndexOf(' ');
    const current = text.slice(cut + 1);
    let pool = sessions;
    try {
        pool = sessions.filter(parseFilterText(text.slice(0, cut + 1)));
    }
    catch {
        // A bad date earlier on: suggest over everything.
    }
    const tally = (fields, match) => {
        const found = [];
        for (const field of fields) {
            const counts = new Map();
            for (const session of pool) {
                const value = field === 'date' ? dayOf(session) : session[field];
                if (value != null)
                    counts.set(value, (counts.get(value) ?? 0) + 1);
            }
            // An id filters by prefix (`acme` keeps `acme-br` too), so its count
            // includes the longer values, which sort right after it.
            const values = [...counts.keys()].sort();
            values.forEach((value, i) => {
                if (!match(value))
                    return;
                let count = counts.get(value);
                for (let j = i + 1; field !== 'date' && j < values.length && values[j].startsWith(value); j++)
                    count += counts.get(values[j]);
                found.push({ token: `${field}:${value}`, count });
            });
        }
        return found.sort((a, b) => b.count - a.count || a.token.localeCompare(b.token));
    };
    const colon = current.indexOf(':');
    const key = colon > 0 ? current.slice(0, colon) : undefined;
    if (FILTER_KEYS.includes(key)) {
        const typed = current.slice(colon + 1);
        // session_id may be typed without its `session-` folder prefix, as in the flag.
        const needles = key === 'session_id' ? [typed, `session-${typed}`] : [typed];
        const values = tally([key], value => needles.some(needle => value.startsWith(needle)));
        return values.filter(s => s.token !== current).slice(0, limit);
    }
    const lower = current.toLowerCase();
    // A field already in the filter is not offered again, neither its name nor its values.
    const used = new Set(text.slice(0, cut + 1).split(/\s+/).filter(word => word.includes(':')).map(word => word.slice(0, word.indexOf(':'))));
    const keys = FIELD_ORDER.filter(name => name.startsWith(lower) && !used.has(name)).map(name => ({ token: `${name}:` }));
    const values = lower === '' ? [] : tally(ID_FIELDS.filter(field => !used.has(field)), value => value.toLowerCase().includes(lower));
    return [...keys, ...values].slice(0, limit);
}

/** The text with its last word replaced by a completion; a value ends the word. */
export function acceptSuggestion(text, token) {
    return text.slice(0, text.lastIndexOf(' ') + 1) + token + (token.endsWith(':') ? '' : ' ');
}

const when = iso => iso.slice(0, 16).replace('T', ' ');
const size = bytes => (bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(1)} KB`);

// Fixed widths: process_id and session_id are uuids, shown whole so they can be copied.
const COLUMNS = [
    { title: 'started (UTC)', width: 16, value: s => when(s.started_at) },
    { title: 'tenant_id', width: 14, value: s => s.tenant_id },
    { title: 'agent_name', width: 16, value: s => s.agent_name ?? '—' },
    { title: 'process_id', width: 36, value: s => s.process_id },
    { title: 'session_id', width: 44, value: s => s.session_id },
    { title: 'size', width: 8, value: s => size(s.bytes) },
];

function line(values, columns) {
    return values.map((value, i) => truncateWidth(value, columns[i].width).padEnd(columns[i].width)).join('  ');
}

export function SessionsScreen({ label, sessions, loading, error, filterText, onFilterText, onOpen, onRefresh, onQuit }) {
    const { columns: termWidth, rows: termHeight } = useTerminalSize();
    const [cursor, setCursor] = React.useState(0);
    // Keys typed fast or pasted arrive in one batch, before a re-render: each
    // key reads and writes the latest mode, draft and pick in these refs, not
    // the rendered values (`/q` typed fast must not quit).
    const [editing, setEditingState] = React.useState(false);
    const editingNow = React.useRef(false);
    const setEditing = on => {
        editingNow.current = on;
        setEditingState(on);
    };
    const [draft, setDraft] = React.useState(filterText);
    const latest = React.useRef(draft);
    const write = text => {
        latest.current = text;
        setDraft(text);
        choose(0);
    };
    const [pick, setPick] = React.useState(0);
    const latestPick = React.useRef(0);
    const choose = index => {
        // max: ↓ with no suggestions yet (still loading) asks for index -1.
        latestPick.current = Math.max(0, index);
        setPick(latestPick.current);
    };

    const shownText = editing ? draft : filterText;
    let filterError;
    let visible = sessions;
    try {
        const keep = parseFilterText(shownText);
        visible = sessions.filter(keep);
    }
    catch (problem) {
        filterError = problem.message;
    }
    const selected = Math.min(cursor, Math.max(0, visible.length - 1));
    const suggestions = editing ? suggestFilter(draft, sessions) : [];
    const picked = Math.min(pick, Math.max(0, suggestions.length - 1));

    // Columns that do not fit are dropped from the right, size first.
    const fitted = [];
    let used = 0;
    for (const column of COLUMNS) {
        if (used + column.width > termWidth - 4)
            break;
        fitted.push(column);
        used += column.width + 2;
    }
    const listHeight = Math.max(3, termHeight - 7 - suggestions.length);
    const top = Math.max(0, Math.min(selected - Math.floor(listHeight / 2), visible.length - listHeight));

    const editKey = (input, key) => {
        const options = suggestFilter(latest.current, sessions);
        const current = Math.min(latestPick.current, Math.max(0, options.length - 1));
        if (key.tab || key.rightArrow) {
            if (options[current] !== undefined)
                write(acceptSuggestion(latest.current, options[current].token));
        }
        else if (key.upArrow)
            choose(Math.max(0, current - 1));
        else if (key.downArrow)
            choose(Math.min(options.length - 1, current + 1));
        else if (key.return) {
            onFilterText(latest.current.trim());
            setEditing(false);
        }
        else if (key.escape) {
            write(filterText);
            setEditing(false);
        }
        else if (key.backspace || key.delete)
            write(latest.current.slice(0, -1));
        else if (input && !key.ctrl && !key.meta)
            write(latest.current + input.replace(/[\x00-\x1f\x7f]/g, ''));
    };

    // ink hands a plain-text chunk over as one input, Tab and Enter inside it
    // included (a paste, keys sent together): split it so they act as keys, and
    // stop at the Enter that ends editing. A lone \n (Ctrl-J) is Enter too.
    const editInput = (input, key) => {
        if (!/[\t\r\n]/.test(input))
            return editKey(input, key);
        for (const char of input) {
            if (!editingNow.current)
                break;
            editKey(char, { tab: char === '\t', return: char === '\r' || char === '\n' });
        }
    };

    useInput((input, key) => {
        if (editingNow.current)
            return editInput(input, key);
        if (input.startsWith('/')) {
            // Ready for the next word: suggestions start at the field names.
            write(filterText === '' ? '' : `${filterText} `);
            setEditing(true);
            // `/tenant_id:t1` typed fast or pasted arrives as one chunk: the rest is the draft.
            if (input.length > 1)
                editInput(input.slice(1), {});
            return;
        }
        if (input === 'q' || key.escape)
            return onQuit();
        if (input === 'r')
            return onRefresh();
        if (key.upArrow || input === 'k')
            return setCursor(Math.max(0, selected - 1));
        if (key.downArrow || input === 'j')
            return setCursor(Math.max(0, Math.min(visible.length - 1, selected + 1)));
        if (key.pageUp)
            return setCursor(Math.max(0, selected - listHeight));
        if (key.pageDown)
            return setCursor(Math.max(0, Math.min(visible.length - 1, selected + listHeight)));
        if (key.home || input === 'g')
            return setCursor(0);
        if (key.end || input === 'G')
            return setCursor(Math.max(0, visible.length - 1));
        if (key.return && visible[selected] !== undefined)
            return onOpen(visible[selected]);
    });

    const count = loading ? 'loading…' : `${visible.length}/${sessions.length} sessions`;
    const width = termWidth - 2;
    const rows = visible.slice(top, top + listHeight);
    let body;
    if (error !== undefined)
        body = _jsx(Text, { color: "error", wrap: "wrap", children: error });
    else if (!loading && visible.length === 0)
        body = _jsx(Text, { color: "subtle", children: sessions.length === 0 ? 'no sessions in this source' : 'no session matches the filter' });
    else
        body = rows.map((session, i) => {
            const isSelected = top + i === selected;
            return _jsx(Text, { wrap: "truncate", color: isSelected ? 'text' : undefined, backgroundColor: isSelected ? 'selectionBg' : undefined, children: line(fitted.map(c => c.value(session)), fitted) }, session.session_id);
        });

    return (_jsxs(Box, { flexDirection: "column", width: "100%", paddingX: 1, children: [
        _jsxs(Box, { width: "100%", justifyContent: "space-between", children: [
            _jsx(Box, { flexShrink: 0, children: _jsx(Text, { color: "accent", bold: true, children: '✦ sessions' }) }),
            // The count first: a long source label is what truncates.
            _jsx(Text, { color: "subtle", wrap: "truncate", children: `  ${count} · ${label}` }),
        ] }),
        _jsx(Box, { height: 1, children: _jsxs(Text, { wrap: "truncate", children: [
            _jsx(Text, { color: editing ? 'suggestion' : 'subtle', children: '/ ' }),
            _jsx(Text, { color: filterError ? 'error' : 'text', children: shownText || (editing ? '' : 'tenant_id:… agent_name:… process_id:… session_id:… date:YYYY-MM-DD[..TO]') }),
            editing ? _jsx(Text, { inverse: true, children: ' ' }) : null,
            filterError ? _jsx(Text, { color: "error", children: `  ${filterError}` }) : null,
        ] }) }),
        ...suggestions.map((s, i) => _jsx(Text, { wrap: "truncate", color: i === picked ? 'suggestion' : 'subtle', children:
            `  ${i === picked ? '▸' : ' '} ${truncateWidth(s.token, 60).padEnd(60)}${s.count === undefined ? '' : `${s.count} session${s.count === 1 ? '' : 's'}`}` }, s.token)),
        _jsx(Divider, { width }),
        _jsx(Text, { color: "subtle", wrap: "truncate", children: line(fitted.map(c => c.title), fitted) }),
        _jsx(Box, { flexDirection: "column", height: listHeight, children: body }),
        _jsx(Divider, { width }),
        _jsx(Text, { color: "subtle", wrap: "truncate", children: _jsx(HintLine, { text: editing
            ? '**↑↓** pick · **Tab** complete · **Enter** apply · **Esc** cancel'
            : '**↑↓** move · **Enter** trajectory · **/** filter · **r** reload · **q** quit' }) }),
    ] }));
}