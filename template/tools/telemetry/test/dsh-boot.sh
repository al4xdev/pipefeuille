#!/usr/bin/env bash
# The SQL plugin inside a real dsh, offline. In a throwaway container of the
# harness image (the pinned dsh; backend_harness/docker.sh build), with this
# folder mounted read-only: a profile `devsql`, a copy of the base profile `app`
# plus dsh-plugin-app-telemetry-sql (its config pointing at a cache built from
# test/fixtures) and the test-only scripted model dsh-boot/dsh-plugin-app-telemetry-probe,
# runs one headless task. The model calls telemetry_schema and telemetry_sql
# (PROBES in its index.js); dsh writes each tool result to the session log, and
# app-telemetry reads that log back: the two reads answer, every refusal comes
# back as a tool error. Nothing is installed in the image itself: the plugin is
# a developer tool, never part of a product profile (README.md).
#   tools/telemetry/test/dsh-boot.sh      needs docker, the image, and `npm ci` here
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
IMAGE="${IMAGE:-app-harness:local}"
[ -d "$HERE/node_modules/@duckdb" ] || { echo "dsh-boot: run npm ci in $HERE first" >&2; exit 2; }
docker image inspect "$IMAGE" >/dev/null 2>&1 || { echo "dsh-boot: no image $IMAGE (backend_harness/docker.sh build)" >&2; exit 2; }

# The workspace path follows app-agent's layout, so app-telemetry lists the session.
script='
set -euo pipefail
T=/work/telemetry
P="$DSH_HOME/profiles"
cp -r "$P/app" "$P/devsql"
# As README.md installs it: the entry names the plugin file by path, nothing is
# linked into dsh'"'"'s own node_modules.
printf -- "- insert:\n    - id: app-telemetry-sql\n      name: $T/dsh-plugin-app-telemetry-sql/index.js\n      config:\n        cacheDir: /tmp/telemetry-cache\n    - id: app-telemetry-probe\n      name: $T/test/dsh-boot/dsh-plugin-app-telemetry-probe/index.js\n" >> "$P/devsql/cordis.patch.yml"
node "$T/bin/app-telemetry.js" --dir "$T/test/fixtures/sessions" --db /tmp/telemetry-cache/local.duckdb sync >&2
work=/tmp/app-work/dev/probe/00000000-0000-4000-8000-0000000000aa
mkdir -p "$work" && cd "$work"
dsh --profile devsql "probe the telemetry tools" >/dev/null 2>/tmp/dsh.err || { cat /tmp/dsh.err >&2; exit 1; }
node "$T/bin/app-telemetry.js" --dir "$DSH_HOME/sessions" --db /tmp/probe.duckdb sql --sync \
  "SELECT name, json_extract_string(arguments, '\''$.query'\'') AS query, tool_is_error, left(result_text, 160) AS result FROM tool_calls ORDER BY seq"
'
out="$(docker run --rm --network none -v "$HERE:/work/telemetry:ro" --entrypoint bash "$IMAGE" -c "$script")"
printf '%s\n' "$out"

# Expected: 7 calls; the first two answer, the other five are refused.
node --input-type=module -e '
  const rows = process.argv[1].split("\n").filter(Boolean).map(line => JSON.parse(line))
  const fail = message => { console.error(`dsh-boot: ${message}`); process.exit(1) }
  if (rows.length !== 7) fail(`expected 7 tool calls, got ${rows.length}`)
  rows.forEach((row, i) => { if (row.tool_is_error !== (i >= 2)) fail(`call ${i} (${row.name} ${row.query ?? ""}): tool_is_error ${row.tool_is_error}`) })
  if (!rows[0].result.includes("\"caches\":[\"local\"]")) fail("telemetry_schema did not list the cache")
  if (!rows[1].result.includes("\"tenant_id\":\"acme\"")) fail("telemetry_sql did not answer")
  for (const [i, pattern] of [[2, /not DELETE/], [3, /file system operations are disabled/], [4, /not ATTACH/], [5, /not SET/], [6, /not a path/]])
    if (!pattern.test(rows[i].result)) fail(`call ${i}: ${rows[i].result}`)
  console.log("dsh-boot: ok (2 reads answered, 5 refusals returned as tool errors, through a real dsh)")
' "$out"
