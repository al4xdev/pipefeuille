import { fileURLToPath } from 'node:url';
import { join } from 'node:path';

// Real sessions of the template harness (backend_harness/tests/e2e: the summarizer
// agent under the offline stub model), copied out of app-harness-local with docker cp.
export const FIXTURES = fileURLToPath(new URL('./fixtures/', import.meta.url));
export const SESSIONS_DIR = join(FIXTURES, 'sessions');

// Two turns (a dispatch, then app-agent resume), tenant with '-' and '_', and a session.lock beside it.
export const TWO_TURNS = {
    tenant_id: 't-1_x', agent_name: 'summarizer',
    process_id: '3b7bfa85-deab-4a77-87c8-e2166c4e41fc', session_id: 'session-c15316e8-d738-4c2b-88c8-faabffb250e0',
    started_at: '2026-11-17T19:43:52.326Z',
    file: join(SESSIONS_DIR, '--tmp-app-work-t-1_x-summarizer-3b7bfa85-deab-4a77-87c8-e2166c4e41fc--',
        'session-c15316e8-d738-4c2b-88c8-faabffb250e0', 'session.v4.jsonl.zstd'),
};
// One turn, tenant acme.
export const ONE_TURN = {
    tenant_id: 'acme', agent_name: 'summarizer',
    process_id: '9931a78c-e6ac-4787-b97c-215cf15b6274', session_id: 'session-a4125d82-169e-4433-8394-b5b977e76dc4',
    started_at: '2026-11-17T19:43:52.412Z',
};
