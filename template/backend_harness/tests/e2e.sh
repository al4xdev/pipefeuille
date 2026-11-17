#!/usr/bin/env bash
# End to end, offline: the image's entrypoint and harness server receive POST
# /dispatch for the example agent `summarizer`, app-agent runs dsh under its
# profile app_summarizer, the agent reads style.md through the workspace fence and
# hands over its summary with finalize_summary, and POST /status reaches
# `completed` with that output and the usage. The model is the test-only stub
# tests/e2e/dsh-plugin-app-e2e-model (an llm/stream middleware), in a derived image
# app-harness:e2e; nothing calls a provider.
#   backend_harness/tests/e2e.sh [--build] [--pg]
# Default: memory queue, container with --network none. --pg: the Postgres queue,
# harness and a postgres:18 container on an --internal docker network (no route
# out). Calls go through `docker exec` (the server listens on the container's
# loopback, as in production).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
HARNESS="$(cd "$HERE/.." && pwd)"
IMAGE="${IMAGE:-app-harness:local}"
TEST_IMAGE=app-harness:e2e
NAME=app-harness-e2e
PG_NAME=app-harness-e2e-pg
NETWORK=app-harness-e2e

build=0 pg=0
for arg in "$@"; do
  case "$arg" in
    --build) build=1 ;;
    --pg) pg=1 ;;
    *) sed -n '2,13p' "$0"; exit 2 ;;
  esac
done
if [ "$build" = 1 ] || ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  "$HARNESS/docker.sh" build
fi
docker build -q --build-arg "BASE=$IMAGE" -t "$TEST_IMAGE" "$HERE/e2e" >/dev/null

cleanup() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  if [ "$pg" = 1 ]; then
    docker rm -f "$PG_NAME" >/dev/null 2>&1 || true
    docker network rm "$NETWORK" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT
cleanup

RUN=(--network none)
if [ "$pg" = 1 ]; then
  docker network create --internal "$NETWORK" >/dev/null
  docker run -d --name "$PG_NAME" --network "$NETWORK" -e POSTGRES_PASSWORD=e2e -e POSTGRES_DB=app postgres:18 >/dev/null
  for i in $(seq 60); do
    docker exec "$PG_NAME" pg_isready -q -h 127.0.0.1 -U postgres -d app 2>/dev/null && break
    [ "$i" != 60 ] || { echo "e2e: postgres did not get ready" >&2; exit 1; }
    sleep 1
  done
  RUN=(--network "$NETWORK" -e "APP_PG_DSN=host=$PG_NAME port=5432 dbname=app user=postgres password=e2e sslmode=disable")
fi
docker run -d --name "$NAME" "${RUN[@]}" "$TEST_IMAGE" >/dev/null

# One HTTP call from inside the container (node's fetch): prints the JSON body.
call() {
  docker exec "$NAME" node -e '
    const [path, body] = process.argv.slice(1)
    fetch(`http://127.0.0.1:8081${path}`, { method: "POST", headers: { "content-type": "application/json" }, body })
      .then(async response => { process.stdout.write(`${response.status} ${await response.text()}\n`) })
      .catch(error => { process.stdout.write(`000 ${error.message}\n`) })' "$1" "$2"
}

for i in $(seq 60); do
  [ "$(call /status '{"tenant_id":"e2e","process_id":"x"}' | cut -c1-3)" = 404 ] && break
  [ "$i" != 60 ] || { echo "e2e: the server did not answer" >&2; docker logs "$NAME" >&2; exit 1; }
  sleep 0.5
done

note='{"agent_name":"summarizer","tenant_id":"e2e","input":{"name":"groceries","text":"Buy milk, eggs and bread before Friday."}}'
answer="$(call /dispatch "$note")"
echo "e2e: POST /dispatch -> $answer"
[ "${answer:0:3}" = 202 ] || exit 1
process_id="$(sed -n 's/.*"process_id":"\([^"]*\)".*/\1/p' <<<"$answer")"

status=""
for i in $(seq 120); do
  status="$(call /status "{\"tenant_id\":\"e2e\",\"process_id\":\"$process_id\"}")"
  case "$status" in *'"status":"completed"'* | *'"status":"failed"'*) break ;; esac
  sleep 0.5
done
echo "e2e: POST /status -> $status"
echo "e2e: server log (structured lines):"
docker logs "$NAME" 2>&1 | { grep -E '"event": ?"(queue_ready|run_ended|answered|limit-reached|request-error)"' || true; } | cut -c1-400 | sed 's/^/  /'
case "$status" in
  *'"status":"completed"'*'The note groceries has 7 words.'* | *'The note groceries has 7 words.'*'"status":"completed"'*) ;;
  *) echo "e2e: FAILED (expected completed with the stub's summary)" >&2
     docker exec "$NAME" sh -c 'cat /tmp/app-work/e2e/*.err' >&2 || true
     exit 1 ;;
esac
grep -q '"input_tokens":200' <<<"$status" || { echo "e2e: FAILED (usage: two stub answers of 100 input tokens)" >&2; exit 1; }
docker logs "$NAME" 2>&1 | grep -q '"turn": 1, "styleRead": true' ||
  { echo "e2e: FAILED (the agent's read of style.md did not return its text)" >&2; exit 1; }
echo "e2e: ok ($([ "$pg" = 1 ] && echo postgres || echo memory) queue)"
