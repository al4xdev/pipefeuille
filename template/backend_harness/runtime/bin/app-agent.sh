#!/usr/bin/env bash
# Shell entrypoint of one agent process:
#   app-agent run    <agent_name> <process_id> <input>   new workspace, new session
#   app-agent resume <process_id> <input>                next turn of that session
#   app-agent check  <template_dir>                      no link of it leaves it (image build)
# The server generates process_id (a uuid) and sets APP_TENANT_ID; local runs
# pass both by hand. The tenant is env, not an argument, because it is the
# server's to decide and resume must stay inside it.
# The workspace /tmp/app-work/<tenant>/<agent_name>/<process_id> is a real
# directory (whatever the process writes stays there, isolated from other processes); its entries,
# hidden ones included (.agents/), are symlinks to the agent's read-only
# template, so dsh finds the agent's AGENTS.md in its cwd.
# dsh names the session folder after that cwd, and it is the only place a
# session copied elsewhere keeps tenant, agent and process: the harness server
# (usage) and any session reader parse
# --tmp-app-work-<tenant>-<agent_name>-<process_id>--, so agent_name has no '-'.
set -euo pipefail
# Byte ranges: in a UTF-8 locale bash's [a-z] / [0-9] match some non-ASCII
# letters and digits, which the server's regexes reject.
export LC_ALL=C

AGENTS=/opt/app/agents
WORK=/tmp/app-work
usage() { sed -n '3,5p' "$0" >&2; exit 2; }

# A template's entries are linked into every workspace, and the fence lets the
# model read what they point to; a link of the template that leaves it would hand
# the model whatever it names (a host file, another tenant's workspace). So no
# link may resolve outside the template, checked at image build and on every run.
check_template() {
  local root link target
  root="$(realpath -e -- "$1")" || { echo "app-agent: no template: $1" >&2; exit 2; }
  while IFS= read -r -d '' link; do
    target="$(realpath -m -- "$link")"
    case "$target" in
      "$root"/*) ;;
      *) echo "app-agent: ${link#"$root"/} in the template of $(basename "$(dirname "$root")") leaves it" >&2; exit 2 ;;
    esac
  done < <(find "$root" -type l -print0)
}

# The input becomes dsh's last argument, and dsh (pinned) re-parses it in the
# booted app even after `--`: one starting with '-' would be read as a flag. The
# server sends a JSON object, so this refuses only what it never sends.
check_input() {
  case "$1" in
    -*) echo "app-agent: the input starts with '-'" >&2; exit 2 ;;
  esac
}

if [ "${1:-}" = check ]; then
  [ $# -eq 2 ] || usage
  check_template "$2"
  exit 0
fi

# The id becomes a path and a session folder name: a lowercase uuid, nothing else.
check_id() {
  if [[ ! "$1" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]]; then
    echo "app-agent: invalid process id: $1" >&2
    exit 2
  fi
}

# The tenant becomes a path segment too: no separators, no dots, at most 64
# (the server's rule; dsh embeds the cwd in its session folder name).
case "${APP_TENANT_ID:-}" in
  '' | *[!A-Za-z0-9_-]*) echo "app-agent: invalid or missing APP_TENANT_ID: ${APP_TENANT_ID:-}" >&2; exit 2 ;;
esac
if [ "${#APP_TENANT_ID}" -gt 64 ]; then
  echo "app-agent: APP_TENANT_ID longer than 64" >&2
  exit 2
fi
TENANT_WORK="$WORK/$APP_TENANT_ID"

# A process_id is unique across agents: find its workspace under any of them.
find_workspace() {
  shopt -s nullglob
  local found=("$TENANT_WORK"/*/"$1")
  shopt -u nullglob
  [ ${#found[@]} -eq 0 ] || printf '%s\n' "${found[@]}"
}

# Each agent runs its own dsh profile, app_<name>, generated at image build
# (app-profiles.mjs): the app profile plus that agent's plugins, so which plugins
# an agent loads is decided here, never by a plugin.
profile_of() {
  if [ ! -f "$DSH_HOME/profiles/app_$1/package.json" ]; then
    echo "app-agent: no dsh profile for agent $1 (app_$1)" >&2
    exit 2
  fi
  printf 'app_%s' "$1"
}

# Opt-in tools (dsh-plugin-app-fs, dsh-plugin-app-sql): the tools.shared of
# agents/<name>/agent.yml (none listed = no tools). It sits outside workspace/,
# so the model never sees it. The profile already inserts only the plugins it
# names; APP_TOOLS is the plugins' second check (defence), read on resume too,
# so a process can't gain tools from its env. dsh-plugin-app-tools checks the
# file against the names the plugins declare; a bad or missing agent.yml stops
# the run (exit 2).
# Its limits too, from the same parser: APP_LIMITS, the JSON of agent.yml's
# limits, which dsh-plugin-app-limits enforces inside dsh (max_run_seconds,
# max_tokens: a notice at 100%, exit 75 = LIMIT_EXCEEDED at 125%).
TOOLS_CLI=/opt/dsh/node_modules/dsh-plugin-app-tools/cli.js
load_agent() {
  APP_TOOLS="$(node "$TOOLS_CLI" "$AGENTS/$1/agent.yml")" || exit 2
  APP_LIMITS="$(node "$TOOLS_CLI" "$AGENTS/$1/agent.yml" limits)" || exit 2
  export APP_TOOLS APP_LIMITS
}

case "${1:-}" in
  run)
    [ $# -eq 4 ] || usage
    name="$2" process_id="$3" input="$4"
    check_id "$process_id"
    check_input "$input"
    # The name becomes a path too (the server's rule): letters, digits and '_',
    # not leading '_' (_shared), at most 64 (the session folder stays under the
    # 251 chars dsh keeps, uuid tail included).
    case "$name" in
      '' | _* | *[!A-Za-z0-9_]*) echo "app-agent: invalid agent name: $name" >&2; exit 2 ;;
    esac
    if [ "${#name}" -gt 64 ]; then
      echo "app-agent: agent name longer than 64" >&2
      exit 2
    fi
    template="$AGENTS/$name/workspace"
    if [ ! -d "$template" ]; then
      echo "app-agent: unknown agent: $name" >&2
      exit 2
    fi
    check_template "$template"
    profile="$(profile_of "$name")" || exit 2
    load_agent "$name"
    workspace="$TENANT_WORK/$name/$process_id"
    # Two runs must never share a workspace: an existing id is an error, and
    # continuing it is what `resume` is for.
    if [ -n "$(find_workspace "$process_id")" ]; then
      echo "app-agent: process $process_id already exists; use resume" >&2
      exit 2
    fi
    mkdir -p "$TENANT_WORK/$name"
    mkdir "$workspace"
    # dotglob: hidden entries too; nullglob: an empty template links nothing.
    shopt -s dotglob nullglob
    for entry in "$template"/*; do
      ln -s "$entry" "$workspace/"
    done
    cd "$workspace"
    exec dsh --profile "$profile" "$input"
    ;;
  resume)
    [ $# -eq 3 ] || usage
    process_id="$2" input="$3"
    check_id "$process_id"
    check_input "$input"
    # Looked up under the caller's tenant only: another tenant's process
    # answers exactly like a missing one.
    mapfile -t found < <(find_workspace "$process_id")
    if [ ${#found[@]} -ne 1 ] || [ ! -d "${found[0]}" ]; then
      echo "app-agent: unknown process: $process_id" >&2
      exit 2
    fi
    workspace="${found[0]}"
    # dsh files sessions under a folder named after the cwd (projectKey: '/'
    # becomes '-'), and refuses to resume from another cwd. The exact name, not
    # a substring match, so no other process's folder can answer. Same
    # container only: sessions live in $DSH_HOME until there is a real store.
    agent_name="$(basename "$(dirname "$workspace")")"
    shopt -s nullglob
    sessions=("$DSH_HOME/sessions/--tmp-app-work-$APP_TENANT_ID-$agent_name-$process_id--"/session-*/)
    if [ ${#sessions[@]} -ne 1 ]; then
      echo "app-agent: process $process_id has ${#sessions[@]} sessions, expected 1" >&2
      exit 1
    fi
    session_id="$(basename "${sessions[0]}")"
    profile="$(profile_of "$agent_name")" || exit 2
    load_agent "$agent_name"
    cd "$workspace"
    exec dsh --profile "$profile" --session-id "$session_id" "$input"
    ;;
  *) usage ;;
esac