#!/usr/bin/env bash
# The one script a developer runs for the agent runtime: builds the image (always,
# cached) and runs it locally. Linux or WSL2 with Docker. `./docker.sh --help`.
# Nothing here reaches a cloud: the only network a run may use is the model
# provider, and only with --model-key (README.md, "Real model runs").
set -euo pipefail

IMAGE="${IMAGE:-app-harness:local}"
PORT="${PORT:-8080}"
# A fixed name makes a second `serve` fail with our message, not docker's.
NAME=app-harness-local
# --pg: a Postgres container on this machine instead of the in-memory queue. Plain
# TCP on a docker network of its own, a fixed local password: the database is on
# that network only (and on 127.0.0.1:$PG_PORT when you ask for it).
PG_NAME=app-pg-local
PG_VOLUME=app-pg-local
PG_NETWORK=app-local
PG_IMAGE=postgres:18
PG_PASSWORD=app-local
PG_DATABASE=app
cd "$(dirname "$0")"

usage() {
  cat >&2 <<'USAGE'
usage: ./docker.sh [--pg [--pg-reset]] [--model-key] [mode] [args...]

  --pg          the Postgres queue instead of memory: container app-pg-local
                (postgres:18, volume app-pg-local, kept across runs), schema
                app_harness, plain TCP on the docker network app-local
  --pg-reset    with --pg: drop that container and its volume first (all data)
  --model-key   pass DEEPSEEK_API_KEY from your environment into the container,
                so agents can call the model. Needs the owner's written
                authorization (README.md, "Real model runs"). Without it every
                model request fails with MISSING_CREDENTIAL: nothing is sent.

modes (default: serve):
  serve                         the HTTP application on http://127.0.0.1:$PORT (8080);
                                the harness server stays on the container's loopback
  agent run NAME ID "input"     one agent through app-agent (ID: a lowercase uuid)
  agent resume ID "input"       its next turn (needs WORK= and SESSIONS=)
  run [args...]                 dsh --profile app
  config                        print the composed dsh profile (app)
  build                         only build the image
  shell                         bash inside the image

knobs: PORT, IMAGE, APP_TENANT_ID (default local), WORK=dir / SESSIONS=dir (mount
the workspaces / dsh sessions on the host), PG_PORT (with --pg: also publish
Postgres on 127.0.0.1:PG_PORT, when the container is created)
USAGE
}

die() {
  printf 'docker.sh: %s\n' "$1" >&2
  shift
  [ $# -eq 0 ] || printf '  %s\n' "$@" >&2
  exit 2
}

pg=0 pg_reset=0 model_key=0
while [ $# -gt 0 ]; do
  case "$1" in
    --pg) pg=1 ;;
    --pg-reset) pg_reset=1 ;;
    --model-key) model_key=1 ;;
    -h | --help) usage; exit 0 ;;
    --*) usage; die "unknown flag: $1" ;;
    *) break ;;
  esac
  shift
done
mode="${1:-serve}"
[ $# -eq 0 ] || shift

case "$mode" in
  build | config | run | agent | serve | shell) ;;
  *) usage; die "unknown mode: $mode" ;;
esac
[ "$pg" = 1 ] || [ "$pg_reset" = 0 ] || die "--pg-reset goes with --pg."
[ "$pg" = 0 ] || [ "$mode" = serve ] || die "--pg is for serve, not $mode."
if [ -n "${PG_PORT:-}" ]; then
  case "$PG_PORT" in *[!0-9]*) die "PG_PORT must be a number, got '$PG_PORT'." ;; esac
fi
if [ "$model_key" = 1 ]; then
  [ -n "${DEEPSEEK_API_KEY:-}" ] || die "--model-key needs DEEPSEEK_API_KEY in your environment."
  case "$mode" in serve | agent | run) ;; *) die "--model-key is for serve, agent and run." ;; esac
fi

command -v docker >/dev/null || die "docker is not installed." "https://docs.docker.com/engine/install/"
docker info >/dev/null 2>&1 || die "the docker daemon is not running, or your user may not use it."

if [ "$mode" = serve ]; then
  case "$PORT" in '' | *[!0-9]*) die "PORT must be a number, got '$PORT'." ;; esac
  [ -z "$(docker ps -q --filter "name=^${NAME}\$")" ] ||
    die "the harness is already running ($NAME)." "Stop it with: docker stop $NAME"
  if (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null; then
    die "port $PORT is already in use." "Free it, or pick another: PORT=8082 ./docker.sh"
  fi
fi

# --- build: always, so the image never lags behind the code (cached: fast) ---
# The named context `logic` is the template root: the Dockerfile copies only its
# pyproject, lock, backend_logic/ and http_adapter/ from it.
docker build -t "$IMAGE" -f Dockerfile --build-context logic=.. . || die "the image build failed (docker's output above)."
[ "$mode" = build ] && exit 0

# --pg: start (or reuse) the Postgres container; the server gets a libpq
# connection string (APP_PG_DSN) to it: plain TCP, admitted because it is a
# container of this machine on a private docker network.
PG_ARGS=()
start_pg() {
  local state i
  if [ "$pg_reset" = 1 ]; then
    echo "docker.sh: --pg-reset: removing $PG_NAME and its volume $PG_VOLUME (all local data)" >&2
    docker rm -f "$PG_NAME" >/dev/null 2>&1 || true
    if docker volume inspect "$PG_VOLUME" >/dev/null 2>&1; then
      docker volume rm "$PG_VOLUME" >/dev/null || die "could not remove the volume $PG_VOLUME (docker's error above)."
    fi
  fi
  docker network inspect "$PG_NETWORK" >/dev/null 2>&1 ||
    docker network create "$PG_NETWORK" >/dev/null || die "could not create the docker network $PG_NETWORK."
  state="$(docker inspect -f '{{.State.Running}}' "$PG_NAME" 2>/dev/null || true)"
  case "$state" in
    true) echo "docker.sh: reusing the running $PG_NAME" >&2 ;;
    false)
      echo "docker.sh: starting $PG_NAME again (its data is in $PG_VOLUME)" >&2
      docker start "$PG_NAME" >/dev/null || die "could not start $PG_NAME." "Start over with: ./docker.sh --pg --pg-reset" ;;
    *)
      echo "docker.sh: creating $PG_NAME ($PG_IMAGE, volume $PG_VOLUME)" >&2
      # postgres 18 keeps its data under /var/lib/postgresql/18/: the volume is the parent.
      docker run -d --name "$PG_NAME" --network "$PG_NETWORK" \
        -v "$PG_VOLUME:/var/lib/postgresql" -e POSTGRES_PASSWORD="$PG_PASSWORD" -e POSTGRES_DB="$PG_DATABASE" \
        ${PG_PORT:+-p "127.0.0.1:$PG_PORT:5432"} "$PG_IMAGE" >/dev/null ||
        die "could not create $PG_NAME (docker's error above)." "If PG_PORT is taken, pick another or leave it unset." ;;
  esac
  docker network connect "$PG_NETWORK" "$PG_NAME" >/dev/null 2>&1 || true
  # Over TCP: while the image initialises a new volume its temporary server listens
  # on the socket only, and is then restarted.
  for i in $(seq 60); do
    docker exec "$PG_NAME" pg_isready -q -h 127.0.0.1 -U postgres -d "$PG_DATABASE" 2>/dev/null && break
    [ "$i" != 60 ] || die "$PG_NAME did not get ready within 60 s." "See: docker logs $PG_NAME"
    sleep 1
  done
  PG_ARGS=(--network "$PG_NETWORK"
    -e "APP_PG_DSN=host=$PG_NAME port=5432 dbname=$PG_DATABASE user=postgres password=$PG_PASSWORD sslmode=disable")
}
[ "$pg" = 0 ] || start_pg

TTY=(-i)
[ -t 0 ] && TTY=(-it)
DSH=(--entrypoint dsh "$IMAGE" --profile app)

case "$mode" in
  config) exec docker run --rm --network none "${DSH[@]}" --dump-config ;;
  shell) exec docker run --rm "${TTY[@]}" --entrypoint bash "$IMAGE" ;;
esac

ARGS=(-e "APP_TENANT_ID=${APP_TENANT_ID:-local}")
[ -n "${WORK:-}" ] && ARGS+=(-v "$WORK:/tmp/app-work")
[ -n "${SESSIONS:-}" ] && ARGS+=(-v "$SESSIONS:/home/node/.dsh/sessions")
# The key goes by name only (-e NAME): its value never appears on a command line.
[ "$model_key" = 0 ] || ARGS+=(-e DEEPSEEK_API_KEY)

case "$mode" in
  run) exec docker run --rm "${TTY[@]}" "${ARGS[@]}" "${DSH[@]}" "$@" ;;
  agent) exec docker run --rm "${TTY[@]}" "${ARGS[@]}" --entrypoint app-agent "$IMAGE" "$@" ;;
esac

{
  echo "docker.sh: queue        $([ "$pg" = 1 ] && echo "postgres $PG_NAME (volume $PG_VOLUME), schema app_harness; psql: docker exec -it $PG_NAME psql -U postgres $PG_DATABASE" || echo "in memory, lost on stop (--pg for Postgres)")"
  echo "           model key    $([ "$model_key" = 1 ] && echo "DEEPSEEK_API_KEY passed (owner-authorized runs only)" || echo "none: model requests fail with MISSING_CREDENTIAL")"
  echo "           image        $IMAGE"
  echo "           url          http://127.0.0.1:$PORT  (the HTTP application: PUT /notes/{name}, POST /notes/{name}/summary, GET /summaries/{run_id}; Ctrl+C to stop)"
} >&2
# Only the HTTP application is published (inside it listens on all interfaces, the
# image's APP_HTTP_HOST), and on the host's loopback only. The harness server stays
# on the container's loopback: nothing outside the container reaches it.
exec docker run --rm "${TTY[@]}" "${ARGS[@]}" "${PG_ARGS[@]}" --name "$NAME" \
  -p "127.0.0.1:$PORT:8080" "$IMAGE" "$@"
