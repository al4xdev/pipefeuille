// Where sessions come from. Every source lists sessions from paths alone (no
// decoding beyond the first frame) and loads one session's bytes on demand.
//   local   the running harness container of backend_harness/docker.sh
//           (app-harness-local), its $DSH_HOME/sessions copied out with `docker cp`
//   dir     a host copy of $DSH_HOME/sessions (docker.sh SESSIONS=dir, a docker cp)
// Both are read-only: nothing is ever written back to a source.
// A session is { source, session_id, tenant_id, agent_name, process_id,
// started_at, updated_at, bytes, file }.
import { spawn } from 'node:child_process';
import { rmSync } from 'node:fs';
import { mkdtemp, readdir, readFile, stat } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, relative } from 'node:path';
import { decodeSession, readHeader } from './decode.js';
import { parseSessionPath, workspaceOf } from './paths.js';

// docker.sh's serve container and where the image keeps dsh's sessions (DSH_HOME).
export const CONTAINER = 'app-harness-local';
export const CONTAINER_SESSIONS = '/home/node/.dsh/sessions';

// Children still running when the tool exits (q, Ctrl-C) are killed with it:
// an abandoned docker cp would otherwise keep running on its own. The local
// copy goes too. Node skips 'exit' on a default-handled signal, so SIGINT and
// SIGTERM exit explicitly; with a listener here, ink's signal-exit no longer
// re-raises the signal either.
const children = new Set();
let localCopy;
function dropLocalCopy() {
    if (localCopy !== undefined)
        rmSync(localCopy, { recursive: true, force: true });
    localCopy = undefined;
}
process.once('exit', () => {
    for (const child of children)
        child.kill('SIGKILL');
    dropLocalCopy();
});
for (const [signal, code] of [['SIGINT', 130], ['SIGTERM', 143]])
    process.once(signal, () => process.exit(code));

/** A child that never answers fails after timeoutMs instead of hanging. */
function run(command, args, { timeoutMs = 120_000 } = {}) {
    return new Promise((resolve, reject) => {
        const child = spawn(command, args, { stdio: ['ignore', 'pipe', 'pipe'] });
        children.add(child);
        const timer = setTimeout(() => {
            child.kill('SIGKILL');
            // A grandchild holding the pipes would keep 'close' from firing
            // and node alive.
            child.stdout.destroy();
            child.stderr.destroy();
            children.delete(child);
            reject(new Error(`${command} did not answer in ${timeoutMs / 1000}s`));
        }, timeoutMs);
        const out = [];
        const err = [];
        child.stdout.on('data', chunk => out.push(chunk));
        child.stderr.on('data', chunk => err.push(chunk));
        child.on('error', error => {
            clearTimeout(timer);
            children.delete(child);
            reject(error.code === 'ENOENT' ? new Error(`${command} not found on PATH`) : error);
        });
        child.on('close', code => {
            clearTimeout(timer);
            children.delete(child);
            resolve({ code, stdout: Buffer.concat(out).toString('utf8'), stderr: Buffer.concat(err).toString('utf8') });
        });
    });
}

const iso = value => new Date(value).toISOString();

async function walk(root) {
    const found = [];
    const visit = async dir => {
        for (const entry of await readdir(dir, { withFileTypes: true }).catch(() => [])) {
            const path = join(dir, entry.name);
            if (entry.isDirectory())
                await visit(path);
            else if (entry.isFile())
                found.push(path);
        }
    };
    await visit(root);
    return found;
}

/** A directory of dsh sessions: `session.v4.jsonl.zstd` files under their dsh folders. */
export function dirSource(root, { kind = 'dir', label = root } = {}) {
    return {
        kind,
        label,
        async list() {
            const sessions = [];
            for (const file of await walk(root)) {
                const ids = parseSessionPath(relative(root, file));
                if (ids === undefined)
                    continue;
                const info = await stat(file);
                // The header knows when the session started, the file mtime when it
                // was last written. A file that does not decode (corrupt, being
                // replaced) keeps the mtime rather than hiding every other session;
                // loading it still fails.
                const updated_at = iso(info.mtimeMs);
                let started_at = updated_at;
                try {
                    const header = readHeader(await readFile(file));
                    if (Number.isSafeInteger(header?.createdAt))
                        started_at = iso(header.createdAt);
                }
                catch {
                    // keep the mtime
                }
                sessions.push({ source: kind, ...ids, started_at, updated_at, bytes: info.size, file });
            }
            return sessions.sort((a, b) => b.started_at.localeCompare(a.started_at));
        },
        async load(session) {
            return readFile(session.file);
        },
    };
}

/**
 * The sessions of the running harness container (docker.sh serve), copied out.
 * One copy per process: a TUI refresh replaces it, and exit or Ctrl-C removes it.
 */
export async function localSource() {
    const { code, stdout, stderr } = await run('docker', ['inspect', '-f', '{{.State.Running}}', CONTAINER]);
    if (code !== 0 || stdout.trim() !== 'true')
        throw new Error(`${CONTAINER} is not running (${(stderr.trim() || 'stopped')}).\nStart it with backend_harness/docker.sh, or read a host copy with --dir PATH.`);
    dropLocalCopy();
    const copy = await mkdtemp(join(tmpdir(), 'app-telemetry-local-'));
    localCopy = copy;
    const copied = await run('docker', ['cp', `${CONTAINER}:${CONTAINER_SESSIONS}`, copy]);
    if (copied.code !== 0)
        throw new Error(copied.stderr.trim() || 'docker cp failed');
    return dirSource(join(copy, 'sessions'), { kind: 'local', label: `${CONTAINER}:${CONTAINER_SESSIONS}` });
}

/** --dir PATH, else the running container (--local, the default). */
export async function openSource({ dir }) {
    return dir !== undefined ? dirSource(dir) : localSource();
}

/**
 * Decoded session: header + events, with the identity fields kept. The header
 * cwd is the unambiguous record of tenant and agent (see paths.js), so it wins
 * over the folder name when both name the same process.
 */
export async function loadSession(source, session) {
    const { header, events } = decodeSession(await source.load(session));
    const workspace = workspaceOf(header?.cwd);
    const identity = workspace?.process_id === session.process_id
        ? { tenant_id: workspace.tenant_id, agent_name: workspace.agent_name } : {};
    return { ...session, ...identity, header, events };
}
