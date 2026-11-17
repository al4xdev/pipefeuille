// Where a session's identity lives: only in its path.
//   <...>/sessions/--tmp-app-work-<tenant_id>-<agent_name>-<process_id>--/<session_id>/session.v4.jsonl.zstd
// dsh's projectKey() writes the cwd /tmp/app-work/<tenant_id>/<agent_name>/<process_id>
// (the workspace backend_harness/runtime/bin/app-agent.sh makes) as that folder
// name and keeps [A-Za-z0-9_-] as-is. process_id is a uuid (the fixed-size tail)
// and agent_name has no '-' (app-agent's rule), so it is the last segment before
// the uuid, and tenant_id, which may contain '-', is the rest. session_id is the
// folder name `session-<uuid>` (app-agent resume passes it back to
// `dsh --session-id`). The header's cwd (workspaceOf) records the same three ids
// unambiguously once the session is loaded.
const UUID = '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}';
const AGENT = '[A-Za-z0-9][A-Za-z0-9_]*';
const SESSION_PATH = new RegExp(
    `(?:^|/)--tmp-app-work-([A-Za-z0-9_-]+)-(${AGENT})-(${UUID})--/(session-${UUID})/session\\.v4\\.jsonl\\.zstd$`);
const WORKSPACE = new RegExp(`^/tmp/app-work/([A-Za-z0-9_-]+)/(${AGENT})/(${UUID})/?$`);

/** { tenant_id, agent_name, process_id, session_id } or undefined for any other path. */
export function parseSessionPath(path) {
    const match = SESSION_PATH.exec(path);
    if (match === null)
        return undefined;
    return { tenant_id: match[1], agent_name: match[2], process_id: match[3], session_id: match[4] };
}

/** { tenant_id, agent_name, process_id } from the header cwd app-agent ran dsh in, or undefined. */
export function workspaceOf(cwd) {
    const match = typeof cwd === 'string' ? WORKSPACE.exec(cwd) : null;
    return match === null ? undefined : { tenant_id: match[1], agent_name: match[2], process_id: match[3] };
}
