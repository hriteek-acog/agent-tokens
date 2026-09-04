# agent-tokens leaderboard skill

Use this skill when the user wants to check token usage, join the org
leaderboard, or debug sync. Keep answers short and run the commands.

## 1. First-time setup (onboarding)

The user links their machine to the org leaderboard once:

```bash
agent-tokens --onboard --email <name@aganitha.ai> --role <role>
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

Every normal run pushes a full all-agent snapshot to the leaderboard server
(HTTPS POST first, SSH file-drop fallback). The dashboard refreshes within
seconds. Display filters never affect what is synced.

## 3. Dashboard

- URL: `https://token-leaderboard.own3.aganitha.ai` (Daily / Weekly tabs)
- Views: overall leaderboard, role-wise board, top harnesses, top models
- Scores are window deltas (latest cumulative minus pre-window baseline)

## 4. Debugging sync

```bash
agent-tokens --me                                    # identity present?
agent-tokens --sync                                  # watch [leaderboard] line on stderr
AGENT_TOKENS_SERVER=https://token-leaderboard.own3.aganitha.ai agent-tokens --sync
curl https://token-leaderboard.own3.aganitha.ai/api/v1/health
curl "https://token-leaderboard.own3.aganitha.ai/api/v1/leaderboard?window=daily"
```

Sync never breaks local display: failures print `[leaderboard] sync skipped (...)`
to stderr and exit code stays 0.

## 5. Anti-cheat notes (for questions about fairness)

- SSH-dropbox files are attributed to the file's UID owner (the SSH login),
  not to any name inside the JSON.
- The dropbox is write-only + sticky: users can create but cannot read, edit,
  or delete each other's files.
- The dashboard reads only the server-owned SQLite DB + append-only ledger;
  raw drop files are consumed once and removed.
- Admin role overrides live in `users.json` (derived from LDAP groups) and
  beat any client-declared role.
- A user inflating their own counters is visible in the ledger (checksums,
  host, timestamps) — see `docs/PROS_CONS.md` for residual risks.
