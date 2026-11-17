// Owner rule: a developer tool, never given to product agents. The product's
// agents come only from backend_harness/ (the image's whole build context, its
// profiles, its agents' agent.yml, docker.sh's containers), so no file there may
// name this tool, its binary or its plugin's tools, except three kinds that never
// reach an agent: docs (*.md), the test-only tests/ folder, and rename-prefix.sh,
// which renames this tool together with the harness. The scanner gets a
// self-test on a synthetic tree, as every gate does.
import { test, after } from 'node:test';
import assert from 'node:assert/strict';
import { mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const HARNESS = fileURLToPath(new URL('../../../backend_harness/', import.meta.url));
// The names a product profile, image or agent would need to reach the tool.
const NAMES = /tools\/telemetry|app-telemetry|dsh-plugin-app-telemetry|telemetry_sql|telemetry_schema/;
const SKIP = new Set(['node_modules', '.venv', '__pycache__', '.mypy_cache', '.pytest_cache', '.ruff_cache']);
const EXEMPT = new Set(['tests', 'rename-prefix.sh']);

/** Files under root (not *.md, not caches) that name the tool: [path, line] pairs. */
export function productReach(root) {
    const found = [];
    const visit = dir => {
        for (const entry of readdirSync(dir, { withFileTypes: true })) {
            const path = join(dir, entry.name);
            if (dir === root && EXEMPT.has(entry.name))
                continue;
            if (entry.isDirectory()) {
                if (!SKIP.has(entry.name))
                    visit(path);
            }
            else if (entry.isFile() && !entry.name.endsWith('.md')) {
                const text = readFileSync(path);
                if (text.includes(0))
                    continue;
                text.toString('utf8').split('\n').forEach((line, i) => {
                    if (NAMES.test(line))
                        found.push(`${relative(root, path)}:${i + 1}`);
                });
            }
        }
    };
    visit(root);
    return found.sort();
}

const scratch = mkdtempSync(join(tmpdir(), 'app-telemetry-placement-'));
after(() => rmSync(scratch, { recursive: true, force: true }));

test('the scanner reports every way a product agent could reach the tool', () => {
    const files = {
        'Dockerfile': 'COPY ../tools/telemetry /opt/telemetry\n',
        'runtime/profiles/app/cordis.patch.yml': '- insert:\n    - id: app-telemetry-sql\n      name: dsh-plugin-app-telemetry-sql\n',
        'agents/x/agent.yml': 'tools:\n  shared: [telemetry_sql]\n',
        'runtime/bin/app-agent.sh': 'exec node /opt/app-telemetry/bin/app-telemetry.js\n',
        'agents/x/workspace/AGENTS.md': 'Use telemetry_schema.\n',
        'docker.sh': 'ARGS+=(-v "$PWD/../tools/telemetry:/opt/telemetry")\n',
        // Allowed: the harness docs may point at the tool; a binary is not read;
        // tests and the rename script at the top only, never deeper.
        'README.md': 'See tools/telemetry.\n',
        'tests/e2e.sh': 'node tools/telemetry/bin/app-telemetry.js\n',
        'rename-prefix.sh': 'TELEMETRY="$HERE/../tools/telemetry"\n',
        'agents/x/tests/probe.sh': 'telemetry_sql\n',
        // dsh's own OTel exporter is not this tool.
        'runtime/profiles/app/other.yml': '- id: session-telemetry-otel\n  disabled: true\n',
    };
    for (const [path, text] of Object.entries(files)) {
        mkdirSync(join(scratch, path, '..'), { recursive: true });
        writeFileSync(join(scratch, path), text);
    }
    writeFileSync(join(scratch, 'blob.bin'), Buffer.from([0, 116, 111, 111, 108, 115, 47, 116, 101, 108, 101, 109, 101, 116, 114, 121]));
    assert.deepEqual(productReach(scratch), [
        'Dockerfile:1', 'agents/x/agent.yml:2', 'agents/x/tests/probe.sh:1', 'docker.sh:1', 'runtime/bin/app-agent.sh:1',
        'runtime/profiles/app/cordis.patch.yml:2', 'runtime/profiles/app/cordis.patch.yml:3',
    ]);
});

test('nothing in backend_harness/ that reaches an agent names the developer tool', () => {
    assert.deepEqual(productReach(HARNESS), []);
});
