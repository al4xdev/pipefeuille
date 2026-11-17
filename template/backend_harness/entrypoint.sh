#!/usr/bin/env bash
# Image entrypoint: the harness server plus every service in /opt/app/services.
# Docker has no systemd, so this script is the service manager: each
# <name>/run.sh starts in the background (name order), the server runs too, and
# SIGTERM is forwarded to all of them. It knows no service by name.
#
# The harness server listens on APP_HARNESS_HOST:APP_HARNESS_PORT (default
# 127.0.0.1:8081, loopback). The logic's HTTP application (http_adapter, under
# /opt/app/web) is the public server, on APP_HTTP_HOST:APP_HTTP_PORT; it starts
# once the harness accepts connections and goes into `servers` next to it.
set -uo pipefail

# One JSON line on stderr per message of this script, like every other process
# of the image. Our texts only need " and \ escaped.
say() {
  local severity=$1 text=$2
  text=${text//\\/\\\\}
  text=${text//\"/\\\"}
  printf '{"severity":"%s","component":"entrypoint","message":"%s"}\n' "$severity" "$text" >&2
}

services=()
for run in /opt/app/services/*/run.sh; do
  [ -e "$run" ] || continue
  bash "$run" &
  services+=($!)
done

# Services get SIGTERM and time for a final pass after the servers are gone, so
# they see all the servers wrote. Bounded: a service stuck in its pass must not
# keep the container alive; after services_grace seconds it is killed.
services_grace=20
stop_services() {
  [ "${#services[@]}" -gt 0 ] || return 0
  kill -TERM "${services[@]}" 2>/dev/null
  local deadline=$((SECONDS + services_grace)) pid
  for pid in "${services[@]}"; do
    while kill -0 "$pid" 2>/dev/null; do
      if [ "$SECONDS" -ge "$deadline" ]; then
        say WARNING "entrypoint: service $pid still running after ${services_grace}s, killed"
        kill -KILL "${services[@]}" 2>/dev/null
        break 2
      fi
      sleep 0.2
    done
  done
  wait "${services[@]}" 2>/dev/null
  return 0
}

port="${APP_HARNESS_PORT:-8081}"
/opt/app/server/.venv/bin/python /opt/app/server/server.py &
harness=$!
servers=("$harness")

# Only the servers on the signal: services are stopped after they are gone.
# Set before the wait below, so a SIGTERM during it ends the harness too.
stopping=0
trap 'stopping=1; kill -TERM "${servers[@]}" 2>/dev/null' TERM INT

# Wait until the harness accepts connections: the HTTP application, started after
# it, must never forward a request to a harness not yet up. Bounded: a
# harness that never listens fails the container instead of serving half of it.
harness_wait=60
deadline=$((SECONDS + harness_wait))
until (: </dev/tcp/127.0.0.1/"$port") 2>/dev/null; do
  if [ "$stopping" = 1 ] || ! kill -0 "$harness" 2>/dev/null; then
    while kill -0 "$harness" 2>/dev/null; do wait "$harness"; done
    wait "$harness"; status=$?
    # Gone before listening, on its own: never report that as a success.
    [ "$stopping" = 1 ] || [ "$status" -ne 0 ] || status=1
    say ERROR "entrypoint: the harness server ended before it listened on $port (status $status)"
    stop_services
    exit "$status"
  fi
  if [ "$SECONDS" -ge "$deadline" ]; then
    say ERROR "entrypoint: the harness server did not listen on $port within ${harness_wait}s"
    kill -TERM "$harness" 2>/dev/null
    while kill -0 "$harness" 2>/dev/null; do wait "$harness"; done
    stop_services
    exit 1
  fi
  sleep 0.2
done

# The public HTTP application: it reaches the harness on loopback only.
(cd /opt/app/web && exec /opt/app/web/.venv/bin/python -m http_adapter.serve) &
servers+=($!)

# The servers are what the container lives for: the first to exit takes the
# others down, and the container exits with its status. A trapped signal
# interrupts `wait` early, so wait again until a server is really gone. A
# service exiting is not fatal.
while :; do
  wait -n "${servers[@]}"; status=$?
  alive=1
  for pid in "${servers[@]}"; do kill -0 "$pid" 2>/dev/null || alive=0; done
  [ "$alive" = 1 ] || break
done
kill -TERM "${servers[@]}" 2>/dev/null
for pid in "${servers[@]}"; do
  while kill -0 "$pid" 2>/dev/null; do wait "$pid"; done
done
stop_services
exit "$status"
