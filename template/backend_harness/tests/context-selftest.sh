#!/usr/bin/env bash
# Self-test of the context gate (context.sh --check): it must FAIL on each of
# its four conditions, and pass on the untouched tree. Offline, like the gate.
#   1. the real check passes (captures every scenario once);
#   2. a baseline diff fails     (a tampered copy of the baselines, REUSE=1);
#   3. a stale baseline fails    (a baseline no scenario captures, REUSE=1);
#   4. a denylisted phrase fails (a denylist naming the probe text, REUSE=1);
#   5. a dead entry fails        (a derived image whose app-limits throws on
#                                 apply, ONLY=app).
#   backend_harness/tests/context-selftest.sh
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
IMAGE="${IMAGE:-app-harness:local}"
scratch="$(mktemp -d)"
trap 'rm -rf "${scratch:?}"; docker image rm -f app-harness:context-selftest >/dev/null 2>&1 || true' EXIT

# expect_fail <label> <pattern> <command...>: the command exits nonzero and says <pattern>.
expect_fail() {
  local label="$1" pattern="$2" status=0
  shift 2
  "$@" >"$scratch/out" 2>&1 || status=$?
  if [ "$status" = 0 ] || ! grep -q -- "$pattern" "$scratch/out"; then
    echo "context-selftest: FAILED: $label (status $status, expected \"$pattern\")" >&2
    tail -20 "$scratch/out" >&2
    exit 1
  fi
  echo "context-selftest: ok: $label"
}

"$HERE/context.sh" --check >"$scratch/out" 2>&1 || { tail -30 "$scratch/out" >&2; echo "context-selftest: the real check fails" >&2; exit 1; }
echo "context-selftest: ok: the untouched tree passes"

cp -r "$HERE/baseline" "$scratch/diff"
printf 'one more line the model does not get\n' >>"$scratch/diff/app.txt"
expect_fail "baseline diff" "differs from" env REUSE=1 BASELINES="$scratch/diff" "$HERE/context.sh" --check

cp -r "$HERE/baseline" "$scratch/stale"
cp "$scratch/stale/app.txt" "$scratch/stale/app.ghost.txt"
expect_fail "stale baseline" "has no scenario" env REUSE=1 BASELINES="$scratch/stale" "$HERE/context.sh" --check

printf '# self-test\ncontext probe\n' >"$scratch/denylist.txt"
expect_fail "denylisted phrase" "DENYLISTED" env REUSE=1 DENYLIST="$scratch/denylist.txt" "$HERE/context.sh" --check

mkdir -p "$scratch/dead"
cat >"$scratch/dead/Dockerfile" <<DOCKERFILE
FROM $IMAGE
USER root
RUN printf '\nexport function apply() { throw new Error("context-selftest: dead entry") }\n' > /tmp/dead.js \
 && sed -i 's/^export function apply(/function original_apply(/' /opt/dsh/node_modules/dsh-plugin-app-limits/index.js \
 && cat /tmp/dead.js >> /opt/dsh/node_modules/dsh-plugin-app-limits/index.js
USER node
DOCKERFILE
docker build -q -t app-harness:context-selftest "$scratch/dead" >/dev/null
expect_fail "dead entry" "did not fully boot" env ONLY=app IMAGE=app-harness:context-selftest "$HERE/context.sh"
echo "context-selftest: ok (the gate fails on each condition)"
