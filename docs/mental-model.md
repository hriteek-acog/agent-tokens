# Mental Model — agent-tokens org leaderboard

## Core Concepts

- **LocalReport**: per-agent token/session totals read from the user's own
  machine (SQLite, JSONL, caches). Read-only, local-first, never locks the agent.
- **Identity**: `{username, email, role}` linked once via `onboard`. Username is
  derived from the email local part; it is a *hint*, not a credential.
- **Snapshot**: one signed JSON document per push — full all-agent totals +
  per-model breakdown + sha256 checksum. It is the only thing that crosses the
  network.
- **Ledger**: append-only server history (SQLite `snapshots` + `ledger.jsonl`).
  Snapshots are never updated or deleted; replays dedupe by checksum.
- **Leaderboard window**: daily (since midnight UTC) or weekly (since Monday UTC).
  Scores are *deltas* — latest cumulative in window minus the baseline just
  before the window — because local counters are cumulative.
- **Dropbox**: write-only sticky inbox on the shared filesystem for the SSH
  fallback. Files are attributed to the file's UID owner (the SSH login), not
  to any name inside the JSON.

## Invariants

- Local display never depends on the network; sync failures never change CLI exit code.
- Display filters never affect what is synced — every push is a FULL all-agent scan.
- The dashboard reads only the server-owned DB; raw drop files never render directly.
- SSH UID (or admin `users.json`) always beats any client-declared username/role.

## Responsibilities

- CLI: measure locally, display locally, push a signed snapshot best-effort.
- Server: validate (schema + checksum + plausibility), append to ledger,
  serve windowed aggregates + single-file dashboard.
- Deploy scripts: create the shared dir with tamper-evident permissions.

## Boundaries

- This system does NOT do billing, cost attribution, or per-prompt tracking.
- It does NOT replace LDAP/OAuth — it leans on SSH + LDAP groups for identity
  and documents the gap (see PROS_CONS.md).
- It does NOT prevent a user from inflating their *own* counters — it makes
  tampering evident (ledger, checksums, host/timestamps) and impossible against
  *others*.

## Relationships

- own3 shared fs (`/shared/hriteek/token-leaderboard`): durable record store.
- LDAP (`ldap.aganitha.ai`): ground truth for users/groups; `users.json` is the
  cached admin mapping.
- Docker host (own3 / US cluster): runs the single `token-leaderboard` container.

## Users

- **Contributor** (any dept): onboards once, runs `agent-tokens` normally, appears on boards.
- **Viewer**: opens the dashboard URL, switches Daily/Weekly, filters by role.
- **Admin**: owns `/shared/hriteek/token-leaderboard`, curates `users.json` from
  LDAP groups, runs the container.
