#!/usr/bin/env bash
# Shared helpers for the scripts in this directory.
#
# Sourced, never executed. Every script here sets `set -euo pipefail` for itself rather
# than inheriting it, so that reading one script tells you how it behaves.

# Colour only when a human is watching. A CI log with escape codes in it is harder to
# read, not easier, and `grep` on a coloured string silently stops matching.
if [[ -t 1 ]]; then
  C_RESET=$'\033[0m'; C_RED=$'\033[31m'; C_GREEN=$'\033[32m'
  C_YELLOW=$'\033[33m'; C_BLUE=$'\033[34m'; C_DIM=$'\033[2m'
else
  C_RESET=""; C_RED=""; C_GREEN=""; C_YELLOW=""; C_BLUE=""; C_DIM=""
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

step()  { printf '\n%s==>%s %s\n' "$C_BLUE" "$C_RESET" "$1"; }
info()  { printf '    %s\n' "$1"; }
note()  { printf '    %s%s%s\n' "$C_DIM" "$1" "$C_RESET"; }
pass()  { printf '  %sok%s   %s\n' "$C_GREEN" "$C_RESET" "$1"; }
warn()  { printf '  %swarn%s %s\n' "$C_YELLOW" "$C_RESET" "$1"; }
fail()  { printf '  %sFAIL%s %s\n' "$C_RED" "$C_RESET" "$1" >&2; }
die()   { fail "$1"; exit "${2:-1}"; }

have() { command -v "$1" >/dev/null 2>&1; }

require() {
  have "$1" || die "$1 is required but not installed. Run scripts/preflight.sh."
}

# Ask before doing something that costs money or is hard to undo. `--yes` skips it, which
# is what CI passes; there is deliberately no way to make that the default.
confirm() {
  local prompt="$1"
  [[ "${ASSUME_YES:-0}" == "1" ]] && return 0
  local reply
  read -r -p "$prompt [y/N] " reply
  [[ "$reply" == "y" || "$reply" == "Y" ]]
}

# Kill a process and everything it spawned, depth first.
#
# `kill $pid` is not enough for either service here: `uvicorn --reload` runs a reloader
# that forks the real worker, and `npm run dev` execs vite as a child. Killing the parent
# orphans the grandchild, which keeps holding the port — and a stale server on :8000 is
# the single most confusing failure in this repository, because the next run tests code
# that is no longer on disk.
kill_tree() {
  local pid="$1" child
  for child in $(pgrep -P "$pid" 2>/dev/null); do
    kill_tree "$child"
  done
  kill "$pid" 2>/dev/null || true
}

# Compare dotted versions: `version_at_least 1.11.0 "$(terraform version)"`.
version_at_least() {
  local want="$1" have="$2"
  [[ "$(printf '%s\n%s\n' "$want" "$have" | sort -V | head -1)" == "$want" ]]
}

# Confirm the caller is not the account root. Every AWS script starts with this: the
# constitution forbids doing work as the owner, and the check costs one API call
# (docs/18 §3.1).
assert_not_root() {
  require aws
  local arn
  arn="$(aws sts get-caller-identity --query Arn --output text 2>/dev/null)" ||
    die "Not authenticated to AWS. Configure a profile, then retry."
  if [[ "$arn" == *":root" ]]; then
    die "You are the account root. Assume a role first — see docs/18 §3.1."
  fi
  # Printed with the account id masked: this repository is public and a terminal
  # recording is one of the easiest ways to leak one (docs/18 §6).
  note "authenticated as ${arn//[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]/<AWS_ACCOUNT_ID>}"
}
