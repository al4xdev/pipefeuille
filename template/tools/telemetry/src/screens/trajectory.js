// dsh-tui's trajectory scene over one decoded session. The scene reads a
// "channel" (a live dsh session in dsh-tui); here it is a frozen snapshot, so
// the fold is built once.
import { jsx as _jsx } from "react/jsx-runtime";
import React from 'react';
import { TrajectoryScene } from '../vendor/screens/TrajectoryScene.js';
import { buildTrajectory } from '../vendor/dsh-adapter/trajectory/index.js';

export function sessionChannel(session, label) {
    const events = Object.freeze(session.events);
    return {
        traceEvents: () => events,
        sessionTitle: `${session.tenant_id} · ${session.agent_name ?? '—'} · ${session.process_id}`,
        cwd: session.header?.cwd ?? '',
        trajectoryBackendLabel: () => label,
        trajectorySource: () => (events.length === 0 ? 'empty' : 'supported'),
    };
}

export function TrajectoryScreen({ session, label, onClose }) {
    const channel = React.useMemo(() => sessionChannel(session, label), [session, label]);
    const build = React.useMemo(() => buildTrajectory(channel.traceEvents()), [channel]);
    return _jsx(TrajectoryScene, { channel, build, onClose });
}