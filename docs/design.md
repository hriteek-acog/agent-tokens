# Design — agent-tokens org leaderboard

## Architecture

One CLI, one server, one shared dir. The CLI keeps its local-first dashboard;
every normal run re-scans ALL providers in the background and pushes one signed
snapshot (SSH file-drop, the authenticated path; HTTPS tried first, automatic
fallback). The server (stdlib-only Python, single container) validates, appends
to an append-only ledger, serves windowed aggregates + a single-file flat light
dashboard. Records live in `/shared/hriteek/token-leaderboard` with create-only
permissions; the SQLite working copy sits on a local volume, rebuilt from the
ledger on startup.

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
**Decision:** `dropbox/` is mode 1733; server attributes to the file UID owner,
dedupes by checksum, deletes after ingest; dashboard never reads raw files.
**Alternatives considered:** World-writable JSON per user — rejected: trivial
history rewriting.
**Consequences:** Tamper-evident, not tamper-proof for one's own numbers.

### Per-(user, host) scoring series
**Status:** Accepted (supersedes plain per-user deltas above)
**Context:** A fresh laptop's lower cumulative totals zeroed the user's whole
score when its push landed last; test fixtures did the same.
**Decision:** Deltas computed per (user, host) series, summed per user.
**Consequences:** Multi-machine users are correct by construction; single-host
stale/low pushes still collapse that host's series (accepted: cumulative
counters have no better oracle).

### INGEST_TOKEN gate on machine HTTPS
**Status:** Accepted
**Context:** Bridge IPs are host-routable, so any cluster user could POST as
anyone, bypassing the LDAP proxy.
**Decision:** `POST /api/v1/ingest` requires `INGEST_TOKEN` (query/header) when
set; production sets it via gitignored `server/.env`. Machines use the SSH
drop; the CLI already falls back on any non-`{"ok": true}` reply.
**Consequences:** HTTPS machine-push is dormant until per-user tokens exist.

### Local SQLite + ledger replay + result cache
**Status:** Accepted
**Context:** SQLite locking is unreliable on NFS-backed `/shared`; per-viewer
10s polling full-scanned the table per request.
**Decision:** DB on a container-local volume (ledger stays the source of truth,
replayed at startup); 5s leaderboard cache, invalidated on ingest.
**Consequences:** Losing the volume costs a rebuild, never data.

---

## Not Doing

- **Per-prompt / cost / billing accounting**: totals only.
- **In-app LDAP login**: proxy layer owns auth; `users.json` is the role bridge.
- **Public internet exposure**: internal host only; container traffic is plain HTTP.
