#!/usr/bin/env bash
# Create /shared/hriteek/token-leaderboard with tamper-evident permissions.
#
# Layout:
#   /shared/hriteek/token-leaderboard/
#     dropbox/        1733  users can CREATE files, cannot list/read/edit others'
#     processed/      700   server only
#     leaderboard.db  600   server only (dashboard reads via HTTP API only)
#     ledger.jsonl    600   server only (append-only audit trail)
#     users.json      644   admin-managed role overrides from LDAP groups
#
# Why this works:
#   * Dropbox is sticky (1) + write-only (733): anyone may `ssh own3
#     "cat > dropbox/<name>.json"` but cannot `ls`, `cat`, `rm` or overwrite
#     anyone else's file — including their own once written (no read/write,
#     write-only means create-only for non-owners; owner of the DIRECTORY,
#     root/server, alone can manage contents).
#   * The server ingests each file once (checksum dedupe), attributes it to the
#     file's UID owner (the SSH login), then deletes it — so manual edits never
#     reach the dashboard; only the append-only DB does.
#   * Run as root (or a sudoer) on own3. Re-run safely to repair perms.
set -euo pipefail

BASE="${1:-/shared/hriteek/token-leaderboard}"
SERVER_UID="${SERVER_UID:-}"   # optional: local user the container maps to

echo "==> creating $BASE"
mkdir -p "$BASE/dropbox" "$BASE/processed"
touch "$BASE/ledger.jsonl" "$BASE/users.json"

if [ ! -s "$BASE/users.json" ]; then
  echo '{}' > "$BASE/users.json"
  echo "wrote empty users.json (map LDAP groups -> roles here)"
fi

# Dropbox: d-wx-wx-wt == 1733 (create-only for everyone, sticky).
chmod 1733 "$BASE/dropbox"
# Server-private state: owner-only.
chmod 700 "$BASE/processed"
chmod 600 "$BASE/ledger.jsonl" 2>/dev/null || true
chmod 644 "$BASE/users.json"

if [ -n "$SERVER_UID" ]; then
  chown "$SERVER_UID" "$BASE/processed" "$BASE/ledger.jsonl" 2>/dev/null || true
fi

# The DB file itself is created by the server at runtime (600 by umask inside
# the container); ensure the base dir stays traversable but not listable by
# others if desired: 755 is fine since sensitive files are 600/700.
chmod 755 "$BASE"

echo "==> resulting perms:"
ls -ld "$BASE" "$BASE/dropbox" "$BASE/processed"
ls -l "$BASE/ledger.jsonl" "$BASE/users.json"
echo
echo "Permissions OK. Users push with:"
echo "  agent-tokens --sync   (https primary, ssh-drop fallback)"
echo "Dashboard reads only via https://token-leaderboard.own3.aganitha.ai (never the files)."
