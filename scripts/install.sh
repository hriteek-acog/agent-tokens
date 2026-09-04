#!/usr/bin/env bash
# One-line setup for agent-tokens (org leaderboard edition).
#
#   bash scripts/install.sh            # from the repo, or:
#   bash <(curl -s https://raw.githubusercontent.com/hriteek-acog/agent-tokens/org-leaderboard/scripts/install.sh)
#
# What it fixes (seen in the wild): pyenv shims resolve `agent-tokens` per
# Python version, so installing under 3.11 leaves the command missing on the
# 3.13 default. This script installs into the CURRENTLY ACTIVE python AND the
# pyenv global default, rehashes shims, and verifies the command resolves —
# so no user has to debug pyenv themselves.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYBINS=()

# 1. Always install into the active interpreter.
PYBINS+=("$(command -v python3)")

# 2. If pyenv exists, also install into the global default version(s).
if command -v pyenv >/dev/null 2>&1; then
  while read -r v; do
    [ -z "$v" ] && continue
    b="$HOME/.pyenv/versions/$v/bin/python3"
    [ -x "$b" ] && PYBINS+=("$b")
  done < <(pyenv global 2>/dev/null | tr ':' '\n' | awk '{print $1}' || true)
fi

# Deduplicate (plain string compare — portable to macOS bash 3.2).
SEEN=""
UNIQ_LIST=""
for b in "${PYBINS[@]}"; do
  real="$(cd "$(dirname "$b")" && pwd -P)/$(basename "$b")"
  case "$SEEN" in
    *"|$real|"*) continue ;;
  esac
  SEEN="$SEEN|$real|"
  UNIQ_LIST="$UNIQ_LIST $real"
done

for py in $UNIQ_LIST; do
  echo "==> installing into $py"
  "$py" -m pip install -e "$REPO_ROOT" 2>&1 | tail -n 1
done

if command -v pyenv >/dev/null 2>&1; then
  pyenv rehash
fi

# 3. Verify the command resolves in THIS shell.
if command -v agent-tokens >/dev/null 2>&1; then
  echo "==> OK: $(agent-tokens --version)"
  echo
  echo "Next: link your identity (once per machine):"
  echo "  agent-tokens --onboard --email you@aganitha.ai --role engineering"
  echo "  agent-tokens doctor    # preflight: identity, server, ssh"
else
  echo "!! agent-tokens still not on PATH. Your shell may not see pyenv shims."
  echo "   Try: export PATH=\"\$HOME/.pyenv/shims:\$PATH\"  (then re-run this script)"
  exit 1
fi
