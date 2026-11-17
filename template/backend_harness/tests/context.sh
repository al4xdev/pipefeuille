#!/usr/bin/env bash
# Show everything the model receives from a fresh `app` agent: system text by
# section, every message, every tool. Offline, no credentials. Three scenarios:
#   app           the first turn
#   app.recovery  the retry after an unexpected failure (app-recovery's notice)
#   app.limit     the turn after a run reached its time limit (app-limits' notice)
# plus one per agent (app.<agent>: its AGENTS.md and its tools, booted under its
# generated profile app_<agent>, as app-agent runs it), for every folder
# backend_harness/agents/<agent>/workspace: a new agent is captured
# (and, without a baseline yet, fails --check) with no edit here.
#   backend_harness/tests/context.sh [--build]           capture only
#   backend_harness/tests/context.sh [--build] --check   capture, then fail on
#                                     a denylisted phrase, a diff from the baselines,
#                                     or a baseline no scenario captures any more
#   backend_harness/tests/context.sh [--build] --update  accept the captures as
#                                     the new baselines (only with the owner's OK)
# Writes <template>/.dumps/harness-context/<scenario>.txt (readable), .json (raw
# request), .stderr. The baselines are tests/baseline/<scenario>.txt.
# Rules of the gate: README.md (backend_harness), "The model context is controlled".
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
HARNESS="$(cd "$HERE/.." && pwd)"
# .dumps/ of the template root: gitignored scratch.
OUT="$(cd "$HARNESS/.." && pwd)/.dumps/harness-context"
BASELINES="${BASELINES:-$HERE/baseline}"
DENYLIST="${DENYLIST:-$HERE/denylist.txt}"
IMAGE="${IMAGE:-app-harness:local}"
# For context-selftest.sh only, never for a real check: REUSE=1 checks the
# captures already in $OUT without capturing again; ONLY="name ..." captures just
# those scenarios (capture mode). BASELINES and DENYLIST point at its tampered copies.

BUILD= MODE=capture
for arg in "$@"; do
  case "$arg" in
    --build)  BUILD=1 ;;
    --check)  MODE=check ;;
    --update) MODE=update ;;
    *) sed -n '2,17p' "$0"; exit 2 ;;
  esac
done

if ! docker info >/dev/null 2>&1; then
  echo "context: docker is not running" >&2
  exit 1
fi
if [ -n "$BUILD" ] || ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  "$HARNESS/docker.sh" build
fi

# The container runs as uid 1000 (node) and writes into $OUT through the mount.
mkdir -p "$OUT"

# capture <name> [context.mjs args...]
capture() {
  local name="$1"; shift
  local status=0
  # --network none: the capture never calls a model, and this proves it.
  docker run --rm --network none \
    -v "$HERE/context.mjs:/app-tools/context.mjs:ro" \
    -v "$OUT:/out" \
    --entrypoint node "$IMAGE" /app-tools/context.mjs --profile app --out /out "$@" \
    2> "$OUT/$name.stderr" || status=$?
  cat "$OUT/$name.stderr" >&2
  [ "$status" = 0 ] || return "$status"
  # An entry that fails to activate is only a boot warning, and the capture
  # never calls the adapter, so a dead provider entry would still yield a "clean"
  # context. Never show or baseline a runtime that did not fully boot.
  if grep -q "did not activate" "$OUT/$name.stderr"; then
    echo "context: $name: the runtime did not fully boot (see above); capture rejected" >&2
    return 1
  fi
  echo "context: $OUT/$name.txt"
}

# check <name>: 0 when clean.
check() {
  local name="$1" failed=0
  # Denylist over model-facing text only (message text, tool descriptions and
  # schemas), not the report header, which names bundles like dsh-base.
  if jq -r '.request | (.messages[].content[] | select(.type == "text") | .text),
            (.tools[]? | .description // "", (.parameters | tojson))' "$OUT/$name.json" \
      | grep -inF -f <(grep -v '^#' "$DENYLIST" | grep -v '^$') > "$OUT/$name.denylist-hits"; then
    echo "context: $name: DENYLISTED phrase reaches the model (fix it at its source):" >&2
    cat "$OUT/$name.denylist-hits" >&2
    failed=1
  fi
  if ! diff -u "$BASELINES/$name.txt" "$OUT/$name.txt" >&2; then
    echo "context: $name: the model context differs from $BASELINES/$name.txt." >&2
    echo "context: review the diff; accept it with --update only after the owner's OK." >&2
    failed=1
  fi
  return "$failed"
}

NAMES=()
# scenario <name> [context.mjs args...]: capture it (unless REUSE or ONLY say no).
scenario() {
  local name="$1"; shift
  NAMES+=("$name")
  [ "${REUSE:-}" != 1 ] || return 0
  [ -z "${ONLY:-}" ] || [[ " $ONLY " == *" $name "* ]] || return 0
  capture "$name" "$@"
}

scenario app
# PROVIDER_TERMINATED stands for any code outside the route's retryPolicy and
# the permanent list: the "unexpected" class app-recovery retries with a notice.
scenario app.recovery --fail-first PROVIDER_TERMINATED --scenario recovery
# A run past its max_run_seconds: app-limits interrupts the turn and sends its
# notice. 60 s: 100% to 125% (where app-limits ends the process with 75) is 15 s,
# 3x the capture's 5 s wait after the request (context.mjs IDLE_WAIT_MS + SETTLE_MS).
scenario app.limit --limit-seconds 60 --scenario limit
# Each agent: its AGENTS.md and the text dsh wraps around it, and its tools
# (agent.yml's tools.shared, its own plugins): their schemas and guidance.
# Name order; the name rule is app-agent's (no leading '_': _shared is no agent).
shopt -s nullglob
AGENT_DIRS=("$HARNESS"/agents/*/workspace/)
shopt -u nullglob
for dir in "${AGENT_DIRS[@]}"; do
  agent="$(basename "$(dirname "$dir")")"
  if [[ ! "$agent" =~ ^[A-Za-z0-9][A-Za-z0-9_]*$ ]]; then
    echo "context: invalid agent name: $agent" >&2
    exit 1
  fi
  scenario "app.$agent" --agent "$agent" --scenario "$agent"
done

case "$MODE" in
  update)
    mkdir -p "$BASELINES"
    for name in "${NAMES[@]}"; do cp "$OUT/$name.txt" "$BASELINES/"; done
    echo "context: baselines updated; commit them with the change that caused them"
    ;;
  check)
    failed=0
    for name in "${NAMES[@]}"; do check "$name" || failed=1; done
    # A baseline nothing captures any more (an agent removed or renamed) would
    # keep vouching for a context nobody gets.
    for baseline in "$BASELINES"/*.txt; do
      name="$(basename "$baseline" .txt)"
      if [[ " ${NAMES[*]} " != *" $name "* ]]; then
        echo "context: $baseline has no scenario (no such agent?): remove it with the change that removed the agent" >&2
        failed=1
      fi
    done
    [ "$failed" = 0 ] && echo "context: check ok (baselines match, no denylisted phrase)"
    exit "$failed"
    ;;
esac