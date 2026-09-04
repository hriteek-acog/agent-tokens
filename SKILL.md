# agent-tokens leaderboard skill

Use this skill when the user wants to check token usage, join the org
leaderboard, or debug sync. Keep answers short and run the commands.

## 1. First-time setup (onboarding)

The user links their machine to the org leaderboard once. If `agent-tokens`
is not found (pyenv), run the installer first — it covers every local Python:

```bash
bash scripts/install.sh   # from the repo clone
agent-tokens --onboard --email <name@aganitha.ai> --role <role>
agent-tokens doctor       # preflight: install, identity, server, ssh
agent-tokens --me
```

Roles: `engineering research design product data qa devops intern other`.
Email must be `@aganitha.ai`. Username is derived from the email prefix and
re-verified server-side against the SSH login / LDAP groups.

## 2. Daily use

```bash
agent-tokens                  # all agents, all time (+ background sync)
agent-tokens --today          # today's activity only (+ background sync)
agent-tokens --codex          # display one agent, still syncs ALL in background
agent-tokens --sync           # force a push now
agent-tokens --no-sync        # display without pushing
```

Every normal run pushes a full all-agent snapshot in the background (display
filters don't affect it). Transport is automatic: HTTPS first, SSH file-drop
to own3 on any failure — behind the LDAP proxy the SSH path is the effective
one (ingested in ~5s). The dashboard refreshes within seconds.

## 3. Dashboard

- URL: `https://token-leaderboard.own3.aganitha.ai` (Daily / Weekly tabs)
- Views: overall leaderboard, role-wise board, top harnesses, top models
- Scores are window deltas (latest cumulative minus pre-window baseline)

## 4. Debugging sync

```bash
agent-tokens --me       # identity present?
agent-tokens --sync     # watch [leaderboard] line on stderr: https vs ssh-drop
ssh own3 "ls -la /shared/hriteek/token-leaderboard/dropbox/"
# file gone within ~10s = ingested; still there = check container logs
```

Sync never breaks local display: failures print `[leaderboard] sync skipped (...)`
to stderr and exit code stays 0.

## 5. Anti-cheat notes (for questions about fairness)

- SSH-dropbox files are attributed to the file's UID owner (the SSH login),
  not to any name inside the JSON.
- The dropbox is write-only + sticky: users can create but cannot read, edit,
  or delete each other's files.
- Machine HTTPS ingest needs `INGEST_TOKEN` (server-side secret); without it
  the CLI falls back to the SSH drop. Anonymous browser hits land on LDAP login.
- Admin role overrides live in `users.json` (from LDAP groups) and beat any
  client-declared role. Self-inflation shows in the ledger — motivational
  board, not payroll-grade (see `docs/PROS_CONS.md`).
