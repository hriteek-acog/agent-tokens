# Architecture pros & cons — agent-tokens org leaderboard

## What was built

`agent-tokens` (local CLI, 12 harnesses) + one stdlib-only leaderboard server
(single Docker container on own3 / US cluster) + `/shared/hriteek/token-leaderboard`
record store. Every CLI run pushes a full signed snapshot (HTTPS primary, SSH
file-drop fallback); the dashboard shows Daily / Weekly overall, role-wise, harness,
and model boards in a dark benchmark-style UI.

## Pros

1. **Zero-friction adoption.** `pip install -e .` + one `onboard` command; afterwards
   every normal run syncs silently in the background. Display filters don't affect
   sync, so partial-agent views still contribute full data.
2. **Instant updates with offline fallback.** HTTPS POST reflects in the dashboard
   within seconds (10s auto-refresh); when the network/API is down, the SSH drop
   (`ssh own3 "cat > dropbox/…"`) still lands and is ingested within ~5s by the poller.
3. **No new dependencies.** Server is stdlib-only (`http.server` + `sqlite3`); the
   image is `python:3.11-slim` + two files. It runs on any cluster host with Docker
   and no PyPI access.
4. **Tamper-evident by construction.** Checksums reject truncation; checksum dedupe
   makes replays harmless; the dashboard reads only the server-owned SQLite DB, never
   raw drop files; the dropbox is write-only + sticky (1733) so nobody can read,
   edit, or delete anyone else's submission; SSH ingest attributes to the file UID
   owner, and admin `users.json` (from LDAP groups) overrides client roles.
5. **Honest scoring.** Window deltas (`latest_in_window − baseline_before_window`)
   make daily/weekly boards comparable even though local counters are cumulative and
   some "today" splits are estimates. Same delta math rolls up to harnesses, models,
   and roles.
6. **Follows existing conventions.** Compose file mirrors the pKa layout (labels,
   named network, `unless-stopped`, bind-mount to `/shared/...`); tests stay in the
   repo's unittest style — 88/88 passing including 14 new org tests plus a live
   end-to-end ingest→leaderboard→dashboard check.
7. **Single-file dashboard.** No build step, no npm; open the URL and it works.
   Dark benchmark aesthetic with Aganitha branding, role filter, top-harness/model
   tables.

## Cons / residual risks

1. **Self-inflation is detectable, not preventable.** A user with local root on their
   own laptop can inflate their own counters before pushing (all client-side metering
   has this property). Mitigations in place: append-only ledger with host/timestamps,
   plausibility caps, anomaly-visible history — but no cryptographic attestation of
   the local stores. Treat the board as motivational, not payroll-grade.
2. **HTTPS identity is gated, machines use SSH.** The reverse proxy fronts the
   server with LDAP (anonymous API POSTs 302 to login; the CLI detects that and
   falls back to the SSH drop). Additionally, `POST /api/v1/ingest` requires
   `INGEST_TOKEN` when set (production `server/.env`), so direct container-IP
   POSTs from the cluster that bypass the proxy get 403. Per-user API tokens
   remain the follow-up to make HTTPS a first-class machine transport.
3. **No in-app LDAP login.** Role truth comes from the admin-curated `users.json`
   snapshot of LDAP groups, not a live bind — group changes need a re-sync step.
   Dashboard itself has no login gate in v1 (internal-network assumption); front with
   cluster nginx + LDAP if exposure widens.
4. **Cumulative-to-delta edge cases.** Onboarding day counts the full total as "daily"
   (bootstrap rule); users who don't push during a window vanish from that window;
   clock skew on clients can misplace `collected_at` (server orders by arrival too,
   but window math uses client timestamps). Push cadence = run cadence, so infrequent
   runners have coarser deltas.
5. **SQLite lives off NFS by design.** The DB is a working copy on a
   container-local volume (rebuilt from the append-only ledger on startup);
   only the ledger, dropbox, and `users.json` sit on shared fs. Leaderboard
   results additionally carry a 5s cache (invalidated on ingest) so per-viewer
   10s polling doesn't full-scan the table. Postgres migration only if actually
   observed to be needed.
6. **Shared-fs trust boundary.** Security rests on `setup_shared_dir.sh` being run as
   root and the container's `/data` mount staying server-owned. A mis-chmod or a
   host admin error re-opens hand-editing. Re-run the script after any manual
   intervention on the path.
7. **No TLS in-container.** Traffic to `:8734` is plaintext HTTP; acceptable on the
   trusted cluster network, but use SSH-tunnel or nginx TLS if accessed off-cluster.

## Recommended follow-ups (in order)

1. Reverse-proxy with LDAP auth injecting `?owner=` on ingest + gating the dashboard.
2. Per-user API tokens issued at `onboard` (stored 0600) to bind HTTPS pushes to identity.
3. Nightly `users.json` refresh from `ldapsearch` groups + anomaly digest (10x jumps, multi-host same user).
4. Postgres migration only if write contention or HA is actually observed.
