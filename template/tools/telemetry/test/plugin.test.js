// dsh-plugin-app-telemetry-sql: the tools without dsh (tools.js), then the
// plugin's registration with a stand-in host (index.js). test/dsh-boot.sh runs
// it inside a real dsh.
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { syncCache } from '../src/db.js';
import { dirSource, loadSession } from '../src/sources.js';
import { cachePathOf, cachesIn, render, schema, sql } from '../dsh-plugin-app-telemetry-sql/tools.js';
import { SESSIONS_DIR } from './helpers.js';
import { refusals } from './refusals.js';

const PLUGIN = fileURLToPath(new URL('../dsh-plugin-app-telemetry-sql/index.js', import.meta.url));
let scratch;
let cacheDir;
let config;
const sha = path => createHash('sha256').update(readFileSync(path)).digest('hex');

before(async () => {
    scratch = mkdtempSync(join(tmpdir(), 'app-telemetry-plugin-'));
    cacheDir = join(scratch, 'cache');
    config = { cacheDir };
    const source = dirSource(SESSIONS_DIR);
    await syncCache(join(cacheDir, 'local.duckdb'), await source.list(), session => loadSession(source, session));
    await syncCache(join(cacheDir, 'dir-0123abcd.duckdb'), (await source.list()).filter(s => s.tenant_id === 'acme'), session => loadSession(source, session));
});
after(() => rmSync(scratch, { recursive: true, force: true }));

test('sql answers JSON lines from the named cache, local by default', async () => {
    assert.equal(await sql({ query: 'SELECT tenant_id FROM sessions ORDER BY tenant_id' }, config), '{"tenant_id":"acme"}\n{"tenant_id":"t-1_x"}');
    assert.equal(await sql({ query: 'SELECT count(*) AS n FROM sessions', cache: 'dir-0123abcd' }, config), '{"n":1}');
    assert.equal(await sql({ query: 'SELECT 1 AS x WHERE false' }, config), '(no rows)');
    await assert.rejects(sql({ query: '  ' }, config), /give one read-only SQL query/);
});

test('schema: the caches present, then every table', async () => {
    const [head, ...tables] = (await schema({}, config)).split('\n').map(line => JSON.parse(line));
    assert.deepEqual(head, { cache: 'local', caches: ['dir-0123abcd', 'local'] });
    assert.deepEqual(tables.map(t => t.table), ['events', 'hotspots', 'model_calls', 'rows', 'sessions', 'tool_calls', 'turns']);
});

test('a cache is a name in the cache folder, never a path', () => {
    for (const bad of ['../local', '/etc/passwd', 'local.duckdb', 'Local', '', 'a/b', '.hidden', 'x'.repeat(65)])
        assert.throws(() => cachePathOf(bad, config), /not a path/, bad);
    assert.throws(() => cachePathOf('nope', config), /no cache nope.*caches here: dir-0123abcd, local/);
    assert.throws(() => cachePathOf(undefined, { cacheDir: join(scratch, 'empty') }), /caches here: none/);
    assert.equal(cachePathOf(undefined, config), join(cacheDir, 'local.duckdb'));
    assert.deepEqual(cachesIn(join(scratch, 'missing')), []);
});

test('long answers are cut, and say so', () => {
    const rows = Array.from({ length: 5 }, (_, i) => ({ i }));
    assert.equal(render(rows, { maxRows: 2 }), '{"i":0}\n{"i":1}\n{"truncated":true,"shown":2,"rows":5,"hint":"add LIMIT, or aggregate"}');
    assert.match(render(rows, { maxChars: 10 }), /^\{"i":0\}\n\{"truncated":true,"shown":1,/);
});

for (const what of Object.keys(refusals(''))) {
    test(`the plugin refuses ${what} (the tool's guard), the cache untouched`, async () => {
        const path = join(cacheDir, 'local.duckdb');
        const before = sha(path);
        const dir = mkdtempSync(join(scratch, 'refuse-'));
        for (const [query, refused] of refusals(dir)[what])
            await assert.rejects(sql({ query }, config), refused, query);
        assert.equal(sha(path), before);
        assert.equal(existsSync(`${path}.wal`), false);
        assert.deepEqual(readdirSync(dir), []);
    });
}

// index.js takes @deepseek-ai/dsh-tools from the running dsh (process.argv[1]).
// Here the "dsh" is a script in a folder whose node_modules holds a stand-in
// defineTool, as a real install holds the real one.
function host() {
    const dir = join(scratch, 'host');
    const tools = join(dir, 'node_modules', '@deepseek-ai', 'dsh-tools');
    mkdirSync(tools, { recursive: true });
    writeFileSync(join(tools, 'package.json'), JSON.stringify({ name: '@deepseek-ai/dsh-tools', type: 'module', main: 'index.js' }));
    writeFileSync(join(tools, 'index.js'), 'export const defineTool = options => ({ ...options, definedByHost: true })\n');
    const bin = join(dir, 'fake-dsh.mjs');
    writeFileSync(bin, `
        const plugin = await import(${JSON.stringify(pathToFileURL(PLUGIN).href)})
        const tools = []
        plugin.apply({ tools: { register: tool => tools.push(tool) } }, JSON.parse(process.argv[2]))
        const call = async (name, args) => {
            try { return { ok: await tools.find(t => t.name === name).execute(args, {}) } }
            catch (error) { return { error: error.message } }
        }
        console.log(JSON.stringify({
            name: plugin.name, inject: plugin.inject,
            tools: tools.map(t => ({ name: t.name, host: t.definedByHost, required: Object.keys(t.parameters).filter(k => t.parameters[k].required) })),
            select: await call('telemetry_sql', { query: 'SELECT count(*) AS n FROM sessions' }),
            write: await call('telemetry_sql', { query: 'DROP TABLE sessions' }),
            schema: (await call('telemetry_schema', {})).ok?.split('\\n')[0],
        }))
    `);
    return bin;
}

test('the plugin registers both tools through the host defineTool and runs them', async () => {
    const bin = host();
    const out = await new Promise((resolve, reject) => execFile(process.execPath, [bin, JSON.stringify(config)], { timeout: 60000 },
        (error, stdout, stderr) => (error ? reject(new Error(stderr || error.message)) : resolve(JSON.parse(stdout)))));
    assert.deepEqual(out, {
        name: 'app-telemetry-sql', inject: ['tools'],
        tools: [{ name: 'telemetry_sql', host: true, required: ['query'] }, { name: 'telemetry_schema', host: true, required: [] }],
        select: { ok: '{"n":2}' },
        write: { error: 'sql: only queries run here (SELECT, WITH, FROM, SHOW, DESCRIBE, SUMMARIZE, EXPLAIN), not DROP' },
        schema: '{"cache":"local","caches":["dir-0123abcd","local"]}',
    });
});

test('outside a dsh, the plugin says where dsh-tools was looked for', async () => {
    const error = await new Promise(resolve => execFile(process.execPath, ['--input-type=module', '-e', `await import(${JSON.stringify(pathToFileURL(PLUGIN).href)})`],
        { timeout: 60000, cwd: scratch }, (failed, _stdout, stderr) => resolve(failed ? stderr : '')));
    assert.match(error, /@deepseek-ai\/dsh-tools not found from the running dsh/);
});

test('the plugin never imports sources.js (its exit and signal handlers would bind dsh)', () => {
    const folder = fileURLToPath(new URL('../dsh-plugin-app-telemetry-sql/', import.meta.url));
    const reached = new Set();
    const visit = file => {
        if (reached.has(file))
            return;
        reached.add(file);
        for (const [, spec] of readFileSync(file, 'utf8').matchAll(/(?:from|import\()\s*'(\.[^']+)'/g))
            visit(fileURLToPath(new URL(spec, pathToFileURL(file))));
    };
    for (const file of readdirSync(folder).filter(f => f.endsWith('.js')))
        visit(join(folder, file));
    const names = [...reached].map(file => file.split('/').slice(-2).join('/'));
    assert.ok(names.includes('src/cache.js') && names.includes('src/db.js'), names.join(', '));
    assert.ok(!names.includes('src/sources.js'), names.join(', '));
});
