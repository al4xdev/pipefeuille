#!/usr/bin/env bash
# The harness's own tests, offline:
#   1. the plugin, runner and profile tests (every *.test.mjs under agents/ and
#      runtime/ here) INSIDE the image with --network none, against the plugins and
#      the generated app_<name> profiles as the image installs them (imports by
#      package name resolve only in /opt/dsh/node_modules);
#   2. the harness server's own gates (ruff, ruff format, mypy, pytest), on the
#      host with its own uv project (backend_harness/server);
#   3. the prefix rename's self-test (rename-prefix.sh on a scratch copy).
#   backend_harness/tests/test.sh [--build] [node --test args...]
# No model is called and no credential is read. The context gate is apart:
# tests/context.sh --check. The end-to-end dispatch: tests/e2e.sh.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
HARNESS="$(cd "$HERE/.." && pwd)"
IMAGE="${IMAGE:-app-harness:local}"

if [ "${1:-}" = --build ]; then
  shift
  "$HARNESS/docker.sh" build
elif ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  "$HARNESS/docker.sh" build
fi

echo "test: 1/3 plugins, runner and profiles (in the image, --network none)" >&2
docker run --rm --network none \
  -v "$HERE:/app-tests:ro" \
  -w /app-tests \
  --entrypoint node "$IMAGE" --test "$@" 'agents/**/*.test.mjs' 'runtime/**/*.test.mjs'

echo "test: 2/3 harness server (its own project: ruff, format, mypy, pytest)" >&2
(
  cd "$HARNESS/server"
  uv run --frozen ruff check .
  uv run --frozen ruff format --check .
  uv run --frozen mypy .
  uv run --frozen pytest -q
)

echo "test: 3/3 prefix rename (scratch copy)" >&2
"$HARNESS/rename-prefix.sh" --self-test
echo "test: ok" >&2
