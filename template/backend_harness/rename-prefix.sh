#!/usr/bin/env bash
# Rename the harness prefix `app` (a FILL-IN: every project picks its own) in one
# go, names and contents:
#   ./rename-prefix.sh NEW [DIR...]  DIRs default to this folder (backend_harness) and
#                                    the developer telemetry tool ../tools/telemetry, which
#                                    carries the same prefix (app-telemetry, app-harness-local)
#   ./rename-prefix.sh --self-test   rename a scratch copy of both to `zq` and check it
#
# The prefix is a token, never a word of prose: `app` with no letter or digit
# next to it (app-agent, app_summarizer, dsh-plugin-app-fs, /opt/app, profile
# `app`, scenario app.limit) and `APP_` (APP_TENANT_ID). The one exception is
# dsh's own package dsh-app-boot. Files and folders named with the token are
# renamed too (runtime/profiles/app, runtime/bin/app-agent.sh, the plugin
# folders). Afterwards: rebuild, rerun tests/test.sh, and re-baseline with
# tests/context.sh --update (the captures name the profile) with the owner's OK.
# Keep it working: a new name that does not follow the token form is caught by
# the self-test (tests/test.sh runs it).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
TELEMETRY="$HERE/../tools/telemetry"
# Lower: not after a letter/digit, not dsh's own `dsh-app-`, not before a letter/digit.
LOWER='(?<![A-Za-z0-9])(?<!dsh-)app(?![A-Za-z0-9])'
UPPER='(?<![A-Za-z0-9])APP(?=_)'
EITHER="(?:$LOWER)|(?:$UPPER)"

leftovers() {
  # Text files only; never the caches, venvs or dependencies.
  grep -rIlP --exclude-dir=.venv --exclude-dir=node_modules --exclude-dir=__pycache__ \
    --exclude-dir=.mypy_cache --exclude-dir=.pytest_cache --exclude-dir=.ruff_cache \
    -e "$EITHER" "$1" || true
}

rename() {
  local new="$1" dir="$2" upper path base target
  upper="$(printf '%s' "$new" | tr '[:lower:]' '[:upper:]')"
  # Contents first, then names (deepest first, so a parent renames last).
  while IFS= read -r -d '' path; do
    NEW="$new" NEWU="$upper" perl -pi -e "s/$LOWER/\$ENV{NEW}/g; s/$UPPER/\$ENV{NEWU}/g" "$path"
  done < <(find "$dir" \( -name .venv -o -name node_modules -o -name __pycache__ -o -name '.*_cache' \) -prune \
             -o -type f -print0 | xargs -0 grep -IlZP -e "$EITHER" 2>/dev/null)
  while IFS= read -r -d '' path; do
    base="$(basename "$path")"
    target="$(dirname "$path")/$(NEW="$new" perl -pe "s/$LOWER/\$ENV{NEW}/g" <<<"$base")"
    [ "$target" = "$path" ] || mv "$path" "$target"
  done < <(find "$dir" -depth \( -name .venv -o -name node_modules -o -name __pycache__ -o -name '.*_cache' \) -prune \
             -o -print0 | grep -zP "/[^/]*$LOWER[^/]*$" || true)
}

if [ "${1:-}" = --self-test ]; then
  scratch="$(mktemp -d)"
  trap 'rm -rf "${scratch:?}"' EXIT
  # The same layout as the template (backend_harness/ beside tools/telemetry/), so
  # the copy renames both with its own defaults, as a project would.
  mkdir -p "$scratch/t/tools"
  cp -a "$HERE" "$scratch/t/backend_harness"
  rm -rf "$scratch/t/backend_harness/server/.venv"
  h="$scratch/t/backend_harness" tel="$scratch/t/tools/telemetry"
  if [ -d "$TELEMETRY" ]; then
    mkdir "$tel"
    # node_modules stays out of the copy, as it stays out of the rename.
    tar -C "$TELEMETRY" --exclude=./node_modules -cf - . | tar -C "$tel" -xf -
  fi
  "$h/rename-prefix.sh" zq >/dev/null
  fail=0
  left="$(leftovers "$scratch/t")"
  [ -z "$left" ] || { echo "rename-prefix: self-test: the token is left in: $left" >&2; fail=1; }
  for expect in runtime/profiles/zq/cordis.patch.yml runtime/bin/zq-agent.sh runtime/bin/zq-profiles.mjs \
      runtime/plugins/dsh-plugin-zq-limits agents/_shared/plugins/dsh-plugin-zq-tools \
      agents/summarizer/plugins/dsh-plugin-zq-summarizer; do
    [ -e "$h/$expect" ] || { echo "rename-prefix: self-test: missing $expect" >&2; fail=1; }
  done
  grep -q "dsh-app-boot" "$h/tests/context.mjs" ||
    { echo "rename-prefix: self-test: dsh's own dsh-app-boot was renamed" >&2; fail=1; }
  grep -q "ZQ_TENANT_ID" "$h/runtime/bin/zq-agent.sh" ||
    { echo "rename-prefix: self-test: APP_TENANT_ID was not renamed" >&2; fail=1; }
  if [ -d "$TELEMETRY" ]; then
    for expect in bin/zq-telemetry.js dsh-plugin-zq-telemetry-sql/index.js \
        test/dsh-boot/dsh-plugin-zq-telemetry-probe/index.js; do
      [ -e "$tel/$expect" ] || { echo "rename-prefix: self-test: missing tools/telemetry/$expect" >&2; fail=1; }
    done
    # The tool reads what the renamed harness writes: its container and workspace names.
    grep -q "'zq-harness-local'" "$tel/src/sources.js" && grep -q -- '--tmp-zq-work-' "$tel/src/paths.js" ||
      { echo "rename-prefix: self-test: tools/telemetry does not follow the harness names" >&2; fail=1; }
    ls "$tel/test/fixtures/sessions" | grep -q -- '^--tmp-zq-work-' ||
      { echo "rename-prefix: self-test: the fixture session folders were not renamed" >&2; fail=1; }
    # The lockfile changes only in the package's own name: an integrity hash that
    # happened to hold the token would break npm ci.
    [ "$(grep -c '"integrity"' "$TELEMETRY/package-lock.json")" -gt 0 ] &&
      diff <(grep '"integrity"' "$TELEMETRY/package-lock.json") <(grep '"integrity"' "$tel/package-lock.json") >/dev/null &&
      [ "$(diff "$TELEMETRY/package-lock.json" "$tel/package-lock.json" | grep -c '^>')" = 3 ] ||
      { echo "rename-prefix: self-test: package-lock.json changed beyond its own name" >&2; fail=1; }
  fi
  [ "$fail" = 0 ] && echo "rename-prefix: self-test ok"
  exit "$fail"
fi

new="${1:-}"
if [[ ! "$new" =~ ^[a-z][a-z0-9]{1,15}$ ]] || [ "$new" = app ] || [ "$new" = dsh ]; then
  sed -n '2,17p' "$0" >&2
  echo "rename-prefix: NEW is ^[a-z][a-z0-9]{1,15}\$ (no '-' or '_': they separate the token), not app or dsh" >&2
  exit 2
fi
shift
dirs=("$@")
if [ ${#dirs[@]} -eq 0 ]; then
  dirs=("$HERE")
  [ -d "$TELEMETRY" ] && dirs+=("$(cd "$TELEMETRY" && pwd)")
fi
for dir in "${dirs[@]}"; do
  rename "$new" "$dir"
  left="$(leftovers "$dir")"
  if [ -n "$left" ]; then
    echo "rename-prefix: the token is still in: $left" >&2
    exit 1
  fi
  echo "rename-prefix: renamed app -> $new under $dir"
done
echo "rename-prefix: rebuild, rerun tests/test.sh and tools/telemetry's npm test, re-baseline (owner's OK)"
