#!/usr/bin/env bash
# One-line setup for agent-tokens (org leaderboard edition).
#
#   bash scripts/install.sh            # from the repo, or:
#   bash <(curl -s https://raw.githubusercontent.com/hriteek-acog/agent-tokens/main/scripts/install.sh)
#
# What it fixes (seen in the wild):
#   * pyenv shims resolve `agent-tokens` per Python version, so installing
#     under 3.11 leaves the command missing on the 3.13 default. Installs into
#     the CURRENTLY ACTIVE python AND the pyenv global default, then rehashes.
#   * Homebrew/system Pythons refuse `pip install` (PEP 668,
#     externally-managed-environment). Retries once with
#     --break-system-packages — safe here: agent-tokens has zero runtime
#     dependencies (stdlib only), so nothing can conflict.
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
  if out="$("$py" -m pip install -e "$REPO_ROOT" 2>&1)"; then
    echo "$out" | tail -n 1
  elif echo "$out" | grep -qi "externally-managed"; then
    echo "    PEP 668 system python detected; retrying with --break-system-packages"
    echo "    (safe: agent-tokens has no runtime dependencies)"
    "$py" -m pip install -e "$REPO_ROOT" --break-system-packages 2>&1 | tail -n 3
  else
    echo "$out" | tail -n 5
    echo "!! install failed for $py (see above)"
    exit 1
  fi
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
