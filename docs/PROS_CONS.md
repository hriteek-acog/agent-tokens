# Architecture pros & cons — agent-tokens org leaderboard

Local CLI (12 harnesses) + one stdlib-only server (single own3 container) +
`/shared/hriteek/token-leaderboard` record store. Every CLI run pushes a full
signed snapshot (SSH file-drop; HTTPS falls back automatically when blocked).
Dashboard: Daily / Weekly overall, role-wise, harness, and model boards in a
flat light benchmark-style UI with the Aganitha logo.

## Pros

1. **Zero-friction adoption.** `install.sh` + one `onboard`; every run syncs
   silently, display filters never affect sync, sync never breaks display.
2. **Fast, offline-tolerant sync.** SSH drop lands in seconds (5s poller, 10s
   dashboard refresh); HTTPS engages automatically wherever the proxy allows.
3. **No dependencies.** Server is stdlib-only; image is `python:3.11-slim` +
   three files. Runs anywhere with Docker, no PyPI needed.
4. **Tamper-evident.** Checksums + dedupe; UID-attributed ingest; admin role
   map beats client claims; 1733 dropbox; append-only ledger; LDAP-gated
   dashboard; token-gated ingest.
5. **Honest scoring.** Per-(user, host) window deltas over cumulative counters —
   a fresh laptop can't zero another machine, multi-machine users sum correctly.

## Cons / residual risks

1. **Self-inflation is detectable, not preventable.** Counters are measured on
   the user's own machine. Ledger (checksums, hosts, timestamps) exposes it —
   treat the board as motivational, not payroll-grade.
2. **Roles aren't live-synced.** `users.json` is a manual snapshot of LDAP
   groups; regroupings need an admin edit.
3. **UTC day boundaries** (05:30 IST cut) and run-cadence granularity:
   onboarding day counts the full total; silent users vanish from the window;
   infrequent runners get coarser deltas.
4. **Shared-fs trust boundary.** Security rests on the dropbox staying 1733,
   the token staying secret, and the proxy labels staying put. Re-run
   `setup_shared_dir.sh` after any manual intervention on the path.
5. **Plaintext inside the cluster.** Public URL is proxy TLS; container traffic
   is plain HTTP — fine on the trusted network, tunnel if accessed wider.

## Follow-ups (in order)

1. Per-user API tokens at `onboard` → HTTPS as a first-class machine transport.
2. Nightly `users.json` refresh from LDAP groups + anomaly digest.
3. Postgres only if the local-volume SQLite is actually observed to strain.
