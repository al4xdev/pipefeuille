/**
 * Trajectory scope — the cross-agent drilldown selector (current agent /
 * delegating turn / all descendants).
 *
 * The scope is a pure value describing WHICH lane's rows the trajectory
 * surfaces render. `session` is the default and the pre-scope behavior;
 * the other three kinds are all anchored on one drilldown target agent:
 *
 *  - `agent`        that agent's own lane log (its tools, its messages);
 *  - `parent-turn`  the MAIN lane's rows of the delegating turn — the
 *                   context the spawn happened in;
 *  - `descendants`  the agent's whole subtree merged in emission order.
 *
 * Pure logic only (no React, no i18n): the surfaces build their chip text
 * from {@link scopeChipParts} and drive the cycle through {@link drillScopeFrom}
 * / {@link nextScope}.
 */
/** The lane's display label: its description, else model, else id head. */
export function laneLabelOf(lane) {
    if (lane.label !== undefined && lane.label !== '')
        return lane.label;
    if (lane.model !== undefined && lane.model !== '')
        return lane.model;
    return lane.agentId.slice(0, 8);
}
/**
 * The lane a ledger row can drill into: a `subagent` descriptor row names
 * its agent directly (the neutral source stamps `agentId`); the
 * DELEGATING tool row anchors one through its `callId`.
 */
export function laneOfNode(node, lanes) {
    if (node === undefined)
        return undefined;
    if (node.agentId !== undefined)
        return lanes.find(lane => lane.agentId === node.agentId);
    if (node.callId !== undefined)
        return lanes.find(lane => lane.callId === node.callId);
    return undefined;
}
/**
 * The MAIN-lane turn a lane's delegating call landed in — the 父回合 a
 * drilldown can jump back to. `undefined` when the anchor call never
 * folded into the main ledger (or the lane registered without a call).
 */
export function parentTurnOf(lane, mainNodes) {
    if (lane.callId === undefined)
        return undefined;
    for (const node of mainNodes) {
        if (node.callId === lane.callId && (node.kind === 'tool' || node.kind === 'subtool'))
            return node.turn;
    }
    return undefined;
}
/** Drill INTO the lane a focused row names; `undefined` = not drillable. */
export function drillScopeFrom(node, lanes) {
    const lane = laneOfNode(node, lanes);
    return lane === undefined ? undefined : { kind: 'agent', agentId: lane.agentId, label: laneLabelOf(lane) };
}
/**
 * The drill key's cycle: 当前 Agent → 父回合 → 全部后代 → 会话. The parent
 * turn is skipped when it cannot be resolved; a scope whose lane vanished
 * (a reset) falls straight back to the session.
 */
export function nextScope(scope, lanes, mainNodes) {
    if (scope.kind === 'session')
        return scope;
    const lane = lanes.find(entry => entry.agentId === scope.agentId);
    if (lane === undefined)
        return { kind: 'session' };
    if (scope.kind === 'agent') {
        const turn = parentTurnOf(lane, mainNodes);
        return turn === undefined
            ? { kind: 'descendants', agentId: lane.agentId, label: laneLabelOf(lane) }
            : { kind: 'parent-turn', agentId: lane.agentId, label: laneLabelOf(lane), turn };
    }
    if (scope.kind === 'parent-turn')
        return { kind: 'descendants', agentId: lane.agentId, label: laneLabelOf(lane) };
    return { kind: 'session' };
}
/** The scope chip's i18n key and interpolation params (`undefined` = hide). */
export function scopeChipParts(scope) {
    switch (scope.kind) {
        case 'agent': return { key: 'trajectory-view-agent', params: { label: scope.label } };
        case 'parent-turn': return { key: 'trajectory-view-parent', params: { turn: scope.turn } };
        case 'descendants': return { key: 'trajectory-view-descendants', params: { label: scope.label } };
        default: return undefined;
    }
}
