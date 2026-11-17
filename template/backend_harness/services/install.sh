#!/usr/bin/env bash
# Build-time installer for every service under this folder (Docker build only).
# A service is any <name>/ with a run.sh; nothing else registers it. Per service:
# a pyproject.toml gets its locked venv on the exact interpreter of its
# .python-version, then its own install.sh runs if present.
set -euo pipefail

cd "$(dirname "$0")"
for run in */run.sh; do
  [ -e "$run" ] || continue
  name="${run%/run.sh}"
  echo "services: installing $name"
  if [ -f "$name/pyproject.toml" ]; then
    python="$(tr -d '[:space:]' < "$name/.python-version")"
    (cd "$name" && uv sync --frozen --no-dev --no-install-project --no-cache --python "$python")
  fi
  if [ -f "$name/install.sh" ]; then
    (cd "$name" && bash ./install.sh)
  fi
done
