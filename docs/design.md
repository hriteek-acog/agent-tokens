# Design — agent-tokens org leaderboard

## Architecture

One CLI, one server, one shared dir. The CLI keeps its local-first dashboard
and adds `onboard / --sync / --me`; every normal run re-scans ALL providers
in the background and pushes one signed snapshot via HTTPS (instant) with an
SSH file-drop fallback (offline-friendly). The server (stdlib-only Python,
single container) validates snapshots, appends them to SQLite + JSONL, polls
the dropbox, and serves windowed aggregates plus a single-file dark
benchmark-style dashboard. Records live in `/shared/hriteek/token-leaderboard`
with write-only sticky permissions so users can submit but never edit.

## Decisions

### Stdlib-only server (no FastAPI/uvicorn dependency)
**Status:** Accepted
**Context:** own3 containers vary; adding web-framework deps complicates the
internal deploy and offline installs.
**Decision:** `server/app.py` uses `http.server.ThreadingHTTPServer` + `sqlite3`
only. Single file, no pip install, runs anywhere Python 3.9+ exists.
**Alternatives considered:** FastAPI (pKa convention) — richer validation/auth
but heavier image and more to secure; rejected for v1, easy to swap later since
the API shape (`POST /api/v1/ingest`, `GET /api/v1/leaderboard`) is framework-free.
**Consequences:** Trivial image, fast review, manual request validation; LDAP-bind
auth stays at the reverse-proxy/layer level (documented, not in-app).

### Window deltas instead of client-reported daily numbers
**Status:** Accepted
**Context:** Local counters are cumulative all-time; some providers only estimate
"today".
**Decision:** Server stores cumulative snapshots and computes
`latest_in_window − latest_before_window` per user/harness/model.
**Alternatives considered:** Trusting client `--today` splits — rejected: estimates
differ per provider and clients could cherry-pick windows.
**Consequences:** Honest cross-user comparison; onboarding-day users score their
full total (documented bootstrap rule).

### SSH UID beats JSON username; admin users.json beats client role
**Status:** Accepted
**Context:** Self-declared names/roles are trivially spoofed.
**Decision:** Dropbox ingest attributes to the file UID owner; `users.json`
(admin-curated from LDAP groups) overrides client role on every ingest.
**Alternatives considered:** Google OAuth on the CLI — heavier UX, still needed a
server session store; deferred.
**Consequences:** Cheating requires compromising the SSH account itself, which is
the org's existing trust boundary.

### Write-only sticky dropbox + consume-once ingest
**Status:** Accepted
**Context:** Requirement: "push via ssh, but nobody hand-edits records".
**Decision:** `dropbox/` is mode 1733; server dedupes by checksum, deletes after
ingest; dashboard never reads raw files.
**Alternatives considered:** World-writable JSON per user — rejected (trivial
history rewriting).
**Consequences:** Tamper-evident (not tamper-proof for one's own numbers —
see PROS_CONS.md); needs `setup_shared_dir.sh` run as root once.

---

## Not Doing

- **Per-prompt / cost / billing accounting**: out of scope; totals only.
- **In-app LDAP password auth**: stays at network/proxy layer for v1; `users.json`
  is the role bridge. Full LDAP-bind login is a documented follow-up.
- **Public internet exposure**: internal host + port only; no TLS termination in
  the container (front with existing cluster nginx if needed).
- **Migrating the test toolchain**: repo stays on unittest + setuptools (existing
  convention); no uv/pytest migration in this change.
