// Where the DuckDB caches live, one file per source: local.duckdb (--local) and
// dir-<hash>.duckdb (--dir PATH). No side effects on import: the dsh plugin
// (dsh-plugin-app-telemetry-sql) loads this inside a dsh process, where
// sources.js's exit and signal handlers must never be installed.
import { homedir } from 'node:os';
import { join } from 'node:path';

export function cacheRoot() {
    return join(process.env.XDG_CACHE_HOME || join(homedir(), '.cache'), 'app-telemetry');
}
