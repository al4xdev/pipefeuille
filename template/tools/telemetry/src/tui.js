// The TUI: sessions → trajectory. Filters given as flags seed the list's filter
// line, so `--tenant_id t1` and typing `tenant_id:t1` land in the same place.
import { jsx as _jsx } from "react/jsx-runtime";
import React from 'react';
import { render, Text, useApp } from 'ink';
import { FILTER_KEYS } from './filters.js';
import { loadSession, openSource } from './sources.js';
import { SessionsScreen } from './screens/sessions.js';
import { TrajectoryScreen } from './screens/trajectory.js';

export function filterTextOf(options) {
    return FILTER_KEYS.filter(key => options[key] !== undefined && options[key] !== '')
        .map(key => `${key}:${options[key]}`).join(' ');
}

export function App({ options }) {
    const { exit } = useApp();
    const [source, setSource] = React.useState();
    const [sessions, setSessions] = React.useState([]);
    const [loading, setLoading] = React.useState(true);
    const [error, setError] = React.useState();
    const [filterText, setFilterText] = React.useState(() => filterTextOf(options));
    const [open, setOpen] = React.useState();  // { session } once loaded, { loading } before

    const refresh = React.useCallback(async () => {
        setLoading(true);
        setError(undefined);
        try {
            // --local copies the container again: a reload sees new sessions.
            const current = await openSource(options);
            setSource(current);
            setSessions(await current.list());
        }
        catch (problem) {
            setError(problem.message);
        }
        finally {
            setLoading(false);
        }
    }, [options]);
    React.useEffect(() => { void refresh(); }, [refresh]);

    const openSession = React.useCallback(async (session) => {
        setOpen({ loading: session.session_id });
        try {
            setOpen({ session: await loadSession(source, session) });
        }
        catch (problem) {
            setOpen(undefined);
            setError(problem.message);
        }
    }, [source]);

    const label = source?.label ?? options.dir ?? 'local';
    // The scene's header shares one line with the title and totals: a long path would push the title out.
    const shortLabel = source?.kind === 'local' ? 'local' : label;
    if (open?.session !== undefined)
        return _jsx(TrajectoryScreen, { session: open.session, label: shortLabel, onClose: () => setOpen(undefined) });
    if (open?.loading !== undefined)
        return _jsx(Text, { color: "gray", children: ` loading ${open.loading}…` });
    return _jsx(SessionsScreen, {
        label, sessions, loading, error, filterText,
        onFilterText: setFilterText, onOpen: openSession, onRefresh: refresh, onQuit: exit,
    });
}

export async function runTui(options) {
    const instance = render(_jsx(App, { options }), { alternateScreen: true, exitOnCtrlC: true });
    await instance.waitUntilExit();
}