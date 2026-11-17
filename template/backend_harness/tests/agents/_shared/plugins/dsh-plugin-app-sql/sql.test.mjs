// dsh-plugin-app-sql against the real DuckDB worker (on the harness server's
// venv, as the image installs it) and a real temp tree laid out like app-fs's
// tests. Runs in the harness image, against the plugins as installed there:
//
//   backend_harness/tests/test.sh

import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { mkdir, mkdtemp, readdir, rm, symlink, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, beforeEach, test } from 'node:test'

const plugins = new URL(`file://${process.env.APP_PLUGINS ?? '/opt/dsh/node_modules/'}`)
const { openWorkspace } = await import(new URL('dsh-plugin-app-fs/workspace.js', plugins))

const { PYTHON, SPILL, Slots, sql } = await import(new URL('dsh-plugin-app-sql/sql.js', plugins))
const { apply } = await import(new URL('dsh-plugin-app-sql/index.js', plugins))

const PID = '11111111-1111-4111-8111-111111111111'
let tmp, work, root, outside, template, ws, slots

beforeEach(async () => {
  tmp = await mkdtemp(join(tmpdir(), 'app-sql-test-'))
  work = join(tmp, 'app-work')
  const agents = join(tmp, 'agents')
  template = join(agents, 'probe', 'workspace')
  await mkdir(template, { recursive: true })
  await writeFile(join(template, 'ref.csv'), 'code,label\n1,one\n')
  root = join(work, 't1', 'probe', PID)
  await mkdir(root, { recursive: true })
  await symlink(join(template, 'ref.csv'), join(root, 'ref.csv'))
  await writeFile(join(root, 't.csv'), 'id,name\n1,a\n2,b\n3,c\n')
  await mkdir(join(root, 'in'))
  // Names that say nothing (or the wrong thing) about the format: it is read from content.
  await writeFile(join(root, 'in', 'tabs-2024'), 'id\tname\n1\ta\n')
  await writeFile(join(root, 'in', 'pipes.dat'), 'id|name\n1|a\n2|b\n')
  await writeFile(join(root, 'in', 'arr.txt'), '\n  [{"id":1},{"id":2}]')
  await writeFile(join(root, 'in', '9lines.log'), '{"id":1}\n{"id":2}\n')
  await writeFile(join(root, 'notes.txt'), 'not a table\n')
  outside = join(tmp, 'outside')
  await mkdir(outside)
  await writeFile(join(outside, 'secret.csv'), 'secret\nouter\n')
  await symlink(join(outside, 'secret.csv'), join(root, 'link.csv'))
  ws = await openWorkspace(root, { env: { APP_TENANT_ID: 't1' }, work, agents })
  slots = new Slots(4)
})

afterEach(() => rm(tmp, { recursive: true, force: true }))

// Test shorthand: a bare path in tables means {path}. The tool itself only takes objects.
const entry = table => (typeof table === 'string' ? { path: table } : table)
const run = (args, signal) => sql(ws, slots, Array.isArray(args.tables) ? { ...args, tables: args.tables.map(entry) } : args, signal)
// What the model would see: the tool's scrubbed text, or its scrubbed error.
const seen = args => run(args).then(out => ({ ok: true, out }), error => ({ ok: false, out: ws.scrub(error), code: error.code }))
// The tool may echo what the model typed (`given`); any other host path is a leak.
const noLeak = (text, given = '') => {
  const rest = text.replaceAll(given, '')
  assert.ok(!rest.includes(tmp) && !rest.includes(PID) && !rest.includes('t1/'), `leaks a host path: ${text}`)
}
const entries = async () => (await readdir(root)).sort()
const spills = () => readdir(SPILL).catch(() => [])

test('reads CSV, TSV, other delimiters, JSON, NDJSON and Parquet by content, from the workspace and the template', async () => {
  execFileSync(PYTHON, ['-I', '-c', "import duckdb; duckdb.connect().execute(\"COPY (SELECT 7 AS id) TO 'pq.csv' (FORMAT parquet)\")"], { cwd: root })
  const out = await run({
    query: 'SELECT (SELECT count(*) FROM t) AS c, (SELECT max(name) FROM tabs_2024) AS t, (SELECT max(name) FROM pipes) AS d, (SELECT count(*) FROM arr) AS j, (SELECT count(*) FROM t_9lines) AS n, (SELECT max(id) FROM pq) AS p, (SELECT label FROM ref) AS r, (SELECT count(*) FROM notes) AS x',
    tables: ['t.csv', 'in/tabs-2024', 'in/pipes.dat', 'in/arr.txt', 'in/9lines.log', 'pq.csv', 'ref.csv', 'notes.txt'],
  })
  assert.equal(out, 'c,t,d,j,n,p,r,x\n3,a,b,2,2,7,one,0\n\n(1 of 1 rows)')
})

test('a file no reader understands fails to load, without a host path', async () => {
  await writeFile(join(root, 'blob'), Buffer.from([0x50, 0x4b, 0x03, 0x04, 0, 0, 0xff, 0xfe, 0, 1, 2, 3]))
  const { ok, out } = await seen({ query: 'SELECT 1', tables: ['blob'] })
  assert.equal(ok, false, out)
  noLeak(out)
})

test('reader options read a Brazilian latin-1 CSV, and DESCRIBE shows the types', async () => {
  await writeFile(join(root, 'br.csv'), Buffer.from('cliente;valor;data\nJoão;1.234,56;31/12/2024\nAção;7,5;01/02/2025\n', 'latin1'))
  const br = { path: 'br.csv', encoding: 'latin-1', delimiter: ';', decimal_separator: ',', thousands: '.', dateformat: '%d/%m/%Y' }
  assert.match(await run({ query: 'DESCRIBE br', tables: [br] }), /^column_name,column_type.*\ncliente,VARCHAR.*\nvalor,DOUBLE.*\ndata,DATE/)
  assert.equal(await run({ query: 'SELECT round(sum(valor), 2) AS s, max(data) AS d, min(cliente) AS c FROM br', tables: [br] }), 's,d,c\n1242.06,2025-02-01,Ação\n\n(1 of 1 rows)')
  // The fallback: everything as text, converted in SQL.
  const raw = { path: 'br.csv', encoding: 'latin-1', all_varchar: true }
  assert.equal(await run({ query: "SELECT sum(TRY_CAST(replace(replace(valor, '.', ''), ',', '.') AS DECIMAL(10,2))) AS s FROM br", tables: [raw] }), 's\n1242.06\n\n(1 of 1 rows)')
  // Without the encoding it fails, and says what to try.
  const { ok, out } = await seen({ query: 'SELECT 1', tables: ['br.csv'] })
  assert.equal(ok, false)
  assert.match(out, /encoding/)
  noLeak(out)
})

test('reader options are checked, bound, and only for delimited text', async () => {
  await writeFile(join(root, 'arr.json'), '[{"id":1}]')
  const bad = [
    { path: 't.csv', sep: ';' },
    { path: 't.csv', delimiter: '' },
    { path: 't.csv', delimiter: ";'); COPY t TO 'x.csv'; --" },
    { path: 't.csv', delimiter: '\n' },
    { path: 't.csv', encoding: 'cp1252' },
    { path: 't.csv', header: 'yes' },
    { path: 't.csv', skip: -1 },
    { path: 't.csv', format: 'xlsx' },
    JSON.parse('{"path": "t.csv", "__proto__": {"delimiter": ";"}}'),
    { path: 'arr.json', delimiter: ';' },
  ]
  const before = await entries()
  for (const table of bad) {
    const { ok, out } = await seen({ query: 'SELECT 1', tables: [table] })
    assert.equal(ok, false, JSON.stringify(table))
    noLeak(out, table.delimiter)
  }
  // Within the limits, a hostile-looking value reaches DuckDB only as a parameter:
  // here, a 4-byte delimiter the file doesn't contain, so one column.
  assert.equal(await run({ query: "SELECT count(*) AS n FROM duckdb_columns() WHERE table_name = 't'", tables: [{ path: 't.csv', delimiter: "';--" }] }), 'n\n1\n\n(1 of 1 rows)')
  assert.deepEqual(await entries(), before)
  assert.equal(await run({ query: 'SELECT count(*) AS n FROM t', tables: [{ path: 't.csv', format: 'csv', header: true, skip: 1 }] }), 'n\n2\n\n(1 of 1 rows)')
})

test('two files with one table name are refused', async () => {
  await writeFile(join(root, 'in', 'T.csv'), 'x\n1\n')
  const { ok, code } = await seen({ query: 'SELECT 1', tables: ['t.csv', 'in/T.csv'] })
  assert.equal(ok, false)
  assert.equal(code, 'APP_SQL_TABLE_NAME')
})

test('table paths go through the fence: escapes read like missing files', async () => {
  for (const path of ['../x.csv', join(outside, 'secret.csv'), '/etc/passwd.csv', 'link.csv', `../../../t2/probe/${PID}/t.csv`, '/proc/self/root/etc/passwd.csv']) {
    const { ok, out, code } = await seen({ query: 'SELECT 1', tables: [path] })
    assert.equal(ok, false, path)
    assert.equal(code, 'APP_FS_NOT_FOUND', `${path}: ${out}`)
    noLeak(out.replaceAll(path, ''))
  }
})

// The shape a critic found: DuckDB reads a path as a pattern, so a workspace file named `*`
// (the model can write one) loaded every entry beside it, the template's links too, and with
// them an outside file and another tenant's. The worker hands DuckDB an open file
// (/proc/self/fd/<n>), never a path: a name with pattern characters is just a name.
test('a table path is a file, never a pattern: `*` and `g[a-z].csv` load as themselves', async () => {
  const sibling = join(work, 't2', 'probe', '22222222-2222-4222-8222-222222222222')
  await mkdir(sibling, { recursive: true })
  await writeFile(join(sibling, 'theirs.csv'), 'secret\nsibling\n')
  // Template links that leave the template (app-agent and the image build refuse them; the
  // worker must not depend on that) and their links in the workspace, as app-agent makes them.
  await symlink(join(outside, 'secret.csv'), join(template, 'x.csv'))
  await symlink(join(sibling, 'theirs.csv'), join(template, 'sib.csv'))
  await symlink(join(template, 'x.csv'), join(root, 'x.csv'))
  await symlink(join(template, 'sib.csv'), join(root, 'sib.csv'))
  await writeFile(join(root, '*'), 'secret\nmine\n')
  await writeFile(join(root, 'g[a-z].csv'), 'id\n1\n')
  await writeFile(join(root, 'gb.csv'), 'id\n2\n3\n')
  const star = await run({ query: 'SELECT * FROM _', tables: [{ path: '*', format: 'csv', header: true }] })
  assert.equal(star, 'secret\nmine\n\n(1 of 1 rows)')
  const literal = await run({ query: 'SELECT count(*) AS n FROM g_a_z_', tables: ['g[a-z].csv'] })
  assert.equal(literal, 'n\n1\n\n(1 of 1 rows)')
  for (const path of ['**/*', '*.csv', 'g?.csv', '{x,sib}.csv', 'x.csv', 'sib.csv']) {
    const { ok, out, code } = await seen({ query: 'SELECT * FROM t', tables: [{ path, format: 'csv' }] })
    assert.equal(ok, false, `${path}: ${out}`)
    assert.equal(code, 'APP_FS_NOT_FOUND', `${path}: ${out}`)
    assert.ok(!out.includes('outer') && !out.includes('sibling'), `${path}: ${out}`)
  }
})

test('the query itself reaches no file, network, extension or setting', async () => {
  const before = await entries()
  const attempts = [
    "FROM read_text('/etc/passwd')",
    `FROM read_csv('${join(outside, 'secret.csv')}')`,
    "FROM read_csv('t.csv')",
    "FROM read_csv('../../../t2/x.csv')",
    "FROM glob('*')",
    "FROM read_csv('https://example.com/x.csv')",
    "COPY t TO 'out.csv'",
    "COPY (SELECT 1) TO '/tmp/app-sql-pwn.csv'",
    "ATTACH 'x.db' AS x",
    "EXPORT DATABASE 'out'",
    'INSTALL httpfs',
    'LOAD httpfs',
    'SET enable_external_access = true',
    "SET memory_limit = '8GB'",
    "PRAGMA memory_limit='8GB'",
    'CALL enable_logging()',
    "SELECT * FROM query('COPY t TO ''q.csv''')",
    "SELECT getenv('APP_TENANT_ID')",
    'CREATE TABLE x AS SELECT 1; COPY x TO \'x.csv\'',
    "CREATE SECRET s (TYPE s3, KEY_ID 'a', SECRET 'b')",
    // The spill folder is the one path DuckDB still allows: no climbing out of it.
    "FROM read_text(current_setting('temp_directory') || '/../../../etc/passwd')",
    "FROM read_text(current_setting('temp_directory') || '/../../app-work/t2/probe/' || 'x/t.csv')",
    "FROM glob(current_setting('temp_directory') || '/../*')",
    "FROM read_text(current_setting('temp_directory') || '-x/../../etc/passwd')",
  ]
  for (const query of attempts) {
    const { ok, out } = await seen({ query, tables: ['t.csv'] })
    assert.equal(ok, false, `${query} -> ${out}`)
    noLeak(out, query.match(/'([^']*)'/)?.[1])
  }
  assert.deepEqual(await entries(), before)
})

test('catalog and settings show no host path', async () => {
  const probes = [
    'SELECT * FROM duckdb_settings()',
    'SELECT * FROM duckdb_tables()',
    'SELECT * FROM duckdb_databases()',
    'SELECT * FROM duckdb_extensions()',
    'SELECT * FROM duckdb_secrets()',
    "SELECT current_setting('allowed_paths'), current_setting('temp_directory')",
    'SELECT * FROM duckdb_temporary_files()',
  ]
  for (const query of probes) {
    const { out } = await seen({ query, tables: ['t.csv'], max_rows: 2000 })
    noLeak(out)
  }
})

test('scratch tables, PIVOT, EXPLAIN and the row cap', async () => {
  assert.match(await run({ query: 'CREATE TABLE s AS SELECT id * 2 AS x FROM t; SELECT sum(x) AS total FROM s', tables: ['t.csv'] }), /^total\n12\n/)
  assert.match(await run({ query: 'PIVOT (SELECT name FROM t) ON name USING count(*)', tables: ['t.csv'] }), /^a,b,c\n1,1,1\n/)
  assert.match(await run({ query: 'EXPLAIN SELECT 1' }), /\(1 of 1 rows\)/)
  assert.match(await run({ query: 'SELECT * FROM range(5000)', max_rows: 3 }), /^range\n0\n1\n2\n\n\(3 of 5000 rows; aggregate/)
})

test('a large result is cut at 50 KiB of whole rows', async () => {
  const out = await run({ query: "SELECT repeat('x', 1000) AS v FROM range(2000)", max_rows: 2000 })
  assert.ok(Buffer.byteLength(out) < 52 * 1024, `${Buffer.byteLength(out)} bytes`)
  assert.match(out, /\((\d+) of 2000 rows; aggregate/)
})

test('the cut keeps rows whole when a cell holds a newline', async () => {
  const out = await run({ query: "SELECT i, repeat('x', 500) || chr(10) || repeat('y', 500) AS v FROM range(2000) t(i)", max_rows: 2000 })
  const [, shown] = out.match(/\((\d+) of 2000 rows; aggregate/)
  const body = out.slice(0, out.lastIndexOf('\n\n('))
  // Header plus `shown` rows, each ending in a whole quoted cell.
  assert.equal(body.split('\n').length, 1 + 2 * Number(shown), body.slice(-80))
  assert.ok(body.endsWith(`${'y'.repeat(500)}"`), body.slice(-80))
})

test('a long query is stopped at its timeout, and its spill folder is removed', async () => {
  const before = await spills()
  const started = Date.now()
  const { ok, code } = await seen({ query: 'SELECT count(*) FROM range(1000000000000) a', timeout_s: 1 })
  assert.equal(ok, false)
  assert.equal(code, 'APP_SQL_STOPPED')
  assert.ok(Date.now() - started < 5000)
  assert.deepEqual(await spills(), before)
})

test('work past memory_mb spills to disk and still answers', async () => {
  const out = await run({ query: 'SELECT count(*) AS n FROM (SELECT i, md5(i::VARCHAR) m FROM range(3000000) t(i) ORDER BY m)', memory_mb: 64 })
  assert.equal(out, 'n\n3000000\n\n(1 of 1 rows)')
})

test('a cancelled call stops its worker', async () => {
  const controller = new AbortController()
  const pending = run({ query: 'SELECT count(*) FROM range(1000000000000) a' }, controller.signal)
  setTimeout(() => controller.abort(), 300)
  await assert.rejects(pending, error => error.code === 'APP_SQL_STOPPED')
})

test('a query past memory_mb fails cleanly', async () => {
  const { ok, out } = await seen({ query: 'SELECT list(range) FROM range(30000000)', memory_mb: 64, timeout_s: 60 })
  assert.equal(ok, false)
  assert.match(out, /memory|Out of Memory|failed/i)
  noLeak(out)
})

test('parallel calls run, at most `size` at once', async () => {
  const results = await Promise.all(Array.from({ length: 6 }, (_, i) => run({ query: `SELECT ${i} AS i, count(*) AS n FROM t`, tables: ['t.csv'] })))
  results.forEach((out, i) => assert.equal(out, `i,n\n${i},3\n\n(1 of 1 rows)`))
  const limited = new Slots(2)
  let now = 0
  let peak = 0
  await Promise.all(Array.from({ length: 6 }, () => limited.run(async () => {
    peak = Math.max(peak, ++now)
    await new Promise(resolve => setTimeout(resolve, 20))
    now -= 1
  })))
  assert.equal(peak, 2)
})

test('bad arguments are refused before a worker starts', async () => {
  const bad = [
    { query: '' },
    { query: 'SELECT 1', tables: { t: 't.csv' } },
    { query: 'SELECT 1', tables: 't.csv' },
    { query: 'SELECT 1', tables: [1] },
    { query: 'SELECT 1', tables: ['in'] },
    { query: 'SELECT 1', tables: Array.from({ length: 17 }, () => 't.csv') },
    { query: 'SELECT 1', memory_mb: 4096 },
    { query: 'SELECT 1', memory_mb: 1.5 },
    { query: 'SELECT 1', timeout_s: 0 },
    { query: 'SELECT 1', max_rows: 1e9 },
    { query: 'x'.repeat(200 * 1024) },
  ]
  for (const args of bad) {
    const { ok, out } = await seen(args)
    assert.equal(ok, false, JSON.stringify(args).slice(0, 80))
    noLeak(out)
  }
  // A bare path is not an entry for the tool itself.
  await assert.rejects(sql(ws, slots, { query: 'SELECT 1', tables: ['t.csv'] }), /list of \{"path"/)
})
// The opt-in's second check: the profile inserts the plugin only for an agent that
// picks sql, and APP_TOOLS (from the same agent.yml, via app-agent) must name it too.
test('the tool registers only when APP_TOOLS names sql', () => {
  const registered = tools => {
    const saved = process.env.APP_TOOLS
    const names = []
    const sections = []
    try {
      if (tools === undefined) delete process.env.APP_TOOLS
      else process.env.APP_TOOLS = tools
      apply({
        tools: { register: tool => names.push(tool.name) },
        systemPrompt: { section: section => sections.push(section.name), getSectionOrder: () => 0 },
      })
    } finally {
      if (saved === undefined) delete process.env.APP_TOOLS
      else process.env.APP_TOOLS = saved
    }
    return { names, sections }
  }
  assert.deepEqual(registered('read,sql'), { names: ['sql'], sections: ['tool:app-sql'] })
  for (const tools of [undefined, '', 'read', 'read,raed', 'SQL']) {
    assert.deepEqual(registered(tools).names, [], String(tools))
  }
})
