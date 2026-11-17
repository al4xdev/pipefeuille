// Queries the cache guard (src/db.js `query`) must refuse, by what they try. The
// sql command and the dsh plugin run the same list, so both prove the same fence.
// `dir` is a scratch folder a query would write into or attach from.
const STATEMENT = /only queries run here/;
const FILES = /file system operations are disabled|only queries run here/;
export function refusals(dir) {
    return {
        writes: [
            ['DELETE FROM events', STATEMENT],
            ["INSERT INTO sessions (session_id) VALUES ('x')", STATEMENT],
            ["UPDATE sessions SET tenant_id = 'x'", STATEMENT],
            ['DROP TABLE events', STATEMENT],
            ['CREATE TEMP TABLE t AS SELECT 1', STATEMENT],
            ['CHECKPOINT', STATEMENT],
            // A refused statement after an allowed one: every statement is checked before any runs.
            ['SELECT 1; DELETE FROM events', /not DELETE/],
            // query() runs a statement given as text: only a single SELECT.
            ["SELECT * FROM query('DELETE FROM events')", /Expected a single SELECT statement/],
        ],
        'file reads and writes': [
            ["SELECT * FROM read_text('/etc/hostname')", /file system operations are disabled/],
            ["SELECT * FROM read_csv('/etc/passwd')", /file system operations are disabled/],
            ["SELECT * FROM read_blob('/etc/hostname')", /file system operations are disabled/],
            ["SELECT * FROM glob('/etc/*')", /file system operations are disabled/],
            [`COPY sessions TO '${dir}/leak.csv'`, FILES],
            [`EXPORT DATABASE '${dir}/export'`, FILES],
        ],
        'settings changes': [
            ['SET enable_external_access = true', STATEMENT],
            ['SET lock_configuration = false', STATEMENT],
            ['RESET lock_configuration', STATEMENT],
            ['PRAGMA enable_profiling', STATEMENT],
            ["SELECT * FROM enable_logging(storage = 'stdout')", /logging functions are not allowed/],
            ["CALL enable_logging(storage = 'file', storage_config = {'path': '/tmp/x'})", /not CALL/],
            // The same function however it is spelled: the check reads DuckDB's parse tree, not the text.
            [`SELECT * FROM "enable_logging"(storage = 'file', storage_config = {'path': '${dir}/log'})`, /logging functions are not allowed/],
            ["SELECT * FROM ENABLE_LOGGING /* c */ (storage = 'stdout')", /logging functions are not allowed/],
            ["SELECT * FROM enable_logging -- c\n(storage = 'stdout')", /logging functions are not allowed/],
            ['SELECT * FROM system.main.truncate_duckdb_logs()', /logging functions are not allowed/],
            ['SELECT (SELECT 1 FROM disable_logging()) AS x', /logging functions are not allowed/],
            // EXPLAIN ANALYZE runs what it explains: checked on that query.
            ["EXPLAIN ANALYZE SELECT * FROM enable_logging(storage = 'stdout')", /logging functions are not allowed/],
            // A query that cannot be serialized is not run, so an EXPLAIN cannot hide one after a plain query.
            ["SELECT 1; EXPLAIN ANALYZE SELECT * FROM enable_logging(storage = 'stdout')", /cannot be checked/],
        ],
        'other databases and extensions': [
            ["ATTACH ':memory:' AS other", STATEMENT],
            [`ATTACH '${dir}/other.duckdb' AS other`, STATEMENT],
            ["SELECT * FROM query('ATTACH '':memory:'' AS other')", /Expected a single SELECT statement/],
            // SQL given as text, out of reach of any check: a logging call assembled from pieces, a table by name.
            ["SELECT * FROM query('SELECT * FROM enable_' || 'logging(storage=''stdout'')')", /run SQL given as text/],
            ["SELECT * FROM query_table('sessions')", /run SQL given as text/],
            ['DETACH cache', STATEMENT],
            ['USE system', STATEMENT],
            ['INSTALL httpfs', STATEMENT],
            ['LOAD httpfs', STATEMENT],
            // An extension function would otherwise auto-install (download) and load its extension.
            [`SELECT * FROM sqlite_scan('${dir}/other.db', 'x')`, /not in the catalog, but it exists in the sqlite_scanner extension/],
        ],
    };
}
