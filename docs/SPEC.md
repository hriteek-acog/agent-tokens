# Implementation Spec — agent-tokens org leaderboard

Complete build spec, start to finish. Follow top to bottom to reimplement the
system from scratch. Versions: CLI `1.3.0`, snapshot schema
`agent-tokens.snapshot/v1`, server `token-board/1.0`.

---

## 1. What this is

A local-first CLI that measures AI coding-agent token usage on each user's own
machine, plus one org-wide leaderboard server. Every CLI run pushes a signed
usage snapshot; the server aggregates Daily/Weekly boards (overall, role-wise,
harness, model) served as a single-page dashboard behind the cluster reverse
proxy (LDAP-gated).

```
┌─────────────┐   HTTPS POST /api/v1/ingest    ┌──────────────────┐   https://<name>.own3.aganitha.ai
│  user laptop │ ──► (LDAP proxy may 302) ──►  │  leaderboard     │ ◄── (LDAP login)
│  agent-tokens│                                │  container:8734  │
│  CLI         │   SSH file-drop fallback       │  SQLite + JSONL  │
└─────────────┘ ──► dropbox/*.json ──poll──►   └──────────────────┘
                                                        ▲ bind mount
                                               /shared/hriteek/token-leaderboard
```

Design principles: local display never depends on the network; display filters
never affect what is synced; dashboard reads only server-owned state; identity
is verified server-side (SSH UID / admin role map), never trusted from the client.

---

## 2. Client: local measurement

### 2.1 Provider model

One module per agent under `src/agent_tokens/providers/`, each implementing
`BaseProvider`:

- `name: str`
- `is_available() -> bool` — true iff the agent's local data store exists
- `get_report(today_only: bool)` — returns `AgentReport` or `None`; must never
  raise to the caller (the CLI wraps each provider in try/except and prints
  `warning: ...` to stderr on failure)

Registry in `providers/__init__.py`: `ALL_PROVIDERS` (12 classes, display order)
and `FLAG_MAP` (CLI flag → class). Supported agents and their local sources:

| Agent | Flag | Local source |
|---|---|---|
| OpenCode | `--opencode` | `~/.local/share/opencode/opencode.db` (`session` table) |
| Claude Code | `--claude` | `~/.claude/stats-cache.json` |
| Antigravity | `--agy` | `~/.gemini/antigravity-cli/conversations/*.db` (protobuf) |
| Codex | `--codex` | `~/.codex/sessions/**/rollout-*.jsonl` |
| Copilot | `--copilot` | `~/.copilot/session-state/*/events.jsonl` + VSCode session-store.db |
| Cursor | `--cursor` | Cursor `workspaceStorage` dirs (sessions only, zero tokens) |
| Gemini CLI | `--gemini` | `~/.gemini/tmp/**/*.json(l)` |
| Qwen Code | `--qwen` | `~/.qwen/tmp/**/*.json(l)` |
| Pi | `--pi` | `~/.pi/agent/**` (excl. `skills/`) |
| DeepSeek | `--deepseek` | `~/.deepseek/**`, `~/.config/deepseek/**` |
| Cline | `--cline` | VSCode `globalStorage/*/tasks/*`, `~/.cline/tasks/*` |
| Windsurf | `--windsurf` | `~/.codeium/chat_state/*.pb` (sessions only, zero tokens) |

Rules: open databases read-only; tools without token counters report activity
with zero tokens (never invent numbers); tolerate schema drift (skip unreadable
files, cap recursion/size when scanning transcript dirs).

### 2.2 Data model (`models.py`)

```python
TokenStats(model_id, input_tokens=0, output_tokens=0, reasoning_tokens=0,
           cache_read_tokens=0, cache_write_tokens=0,
           session_count=0, turn_count=0, last_active=None)
  total_tokens = input + output + reasoning + cache_read + cache_write
SessionInfo(session_id, title, model_id, <same counters>, turn_count=0, updated_at=None)
AgentReport(agent_name, models=[...], recent_sessions=[...])
  total_tokens = sum(model totals)
```

`__post_init__` coerces `None`/float counter artefacts to `int`. Every class has
`to_dict()` including the computed `total_tokens`.

### 2.3 Terminal + JSON formatters (`formatters.py`)

- `render_terminal(reports, time_scope, use_color)`: per-agent sections with a
  model table (Model/Sessions/[Turns]/Input/Output/Reason/Reasoning/Cache/Total),
  top-5 recent sessions, grand total. Honors `NO_COLOR`. **Display-only rule:
  hide models and sessions with `total_tokens == 0`.**
- `render_json(reports)`: unfiltered `to_dict()` list (pipeline fidelity kept).
- `format_number(n)`: `1.25M / 450K / 1,234` compaction; bool/None/negative → `0`.

### 2.4 CLI (`cli.py`)

Flags: `--today`, 12× `--<agent>`, `--json`, `--no-color`, `--version`,
`--onboard --email --role`, `--me`, `--doctor`, `--sync`, `--no-sync`,
`--server <url>`.

Flow in `main()`:
1. `--doctor` → run preflight (§4), exit with its code. `--me` → print identity.
   `--onboard` → validate + persist identity (§3), exit.
2. Display scan: providers for selected flags, else all 12. Render terminal or JSON.
3. Sync (unless `--no-sync`): **full all-12 scan regardless of display filter**,
   build snapshot (§5), push (§6). Any sync exception prints
   `[leaderboard] sync skipped (...)` to stderr; exit code stays 0.

---

## 3. Identity (`identity.py`)

Config file: `$AGENT_TOKENS_CONFIG` or `~/.config/agent-tokens/config.json`
(written `0600`, atomic via `.tmp` + rename). Record:
`{username, email, role, verified}`.

- `validate_email`: lowercase, regex `^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$`,
  domain must be in `ALLOWED_DOMAINS = ("aganitha.ai",)`.
- `username_from_email`: local part, lowercased, `[^a-z0-9._-]` → `-`.
- `validate_role` against `VALID_ROLES = (engineering, research, design,
  product, data, qa, devops, intern, other)`.
- `onboard(email, role)` → validate, derive username, `verified=True`, persist.
- `ldap_group_to_role(groups)`: lowercase group names; first `VALID_ROLES` hit
  wins, else `engineering` if `engineering`/`acog` present, else `other`.
  (Used by admins to build `users.json`, §8.)

The username is a **hint** — §7 explains why it can't be trusted alone.

---

## 4. Setup tooling

### 4.1 `scripts/install.sh` (pyenv-safe)

pyenv shims resolve commands per interpreter, so the script installs into the
active `python3` plus every `pyenv global` version, rehashes, verifies
`agent-tokens --version` resolves, and prints the onboard next step.

### 4.2 `agent-tokens doctor` (`doctor.py`)

Four checks, printed `[OK|WARN|FAIL] <name>: <detail + fix>`:

| Check | OK | WARN | FAIL |
|---|---|---|---|
| install | version + interpreter path | — | (cannot fail; local facts) |
| identity | `user <email> [role]` | — | prints exact `--onboard` command |
| server | `GET /health` returns `{"ok": true}` | non-JSON reply (LDAP gate) or internal-CA TLS error → "SSH-drop still works" | — (never FAIL: informational only) |
| ssh-drop | `ssh <host> "test -d <dir> && touch/rm .doctor"` + `whoami` | — | prints ssh error / fix hint |

Exit 0 unless a FAIL row exists. Uses `BatchMode=yes, ConnectTimeout=8` for ssh.

---

## 5. Snapshot schema (`sync.py::build_snapshot`)

One JSON document per push, `schema = "agent-tokens.snapshot/v1"`:

```json
{
  "schema": "agent-tokens.snapshot/v1",
  "username": "hriteek", "email": "hriteek@aganitha.ai", "role": "engineering",
  "host": "HriteekM1.local", "client_version": "1.3.0",
  "collected_at": "2026-09-04T10:33:06+00:00",
  "total_tokens": 400719903,
  "agents": [{"agent_name": "Claude Code", "total_tokens": 349563477}],
  "models": [{"agent_name": "Claude Code", "model_id": "claude-opus-…",
              "total_tokens": 180793133, "session_count": 12, "turn_count": 0}],
  "checksum": "sha256-hex"
}
```

- Per-model totals use the §2.2 formula; `agents[]` collapses models per agent.
- `checksum` = SHA-256 over canonical JSON of the payload **minus** `checksum`
  (`json.dumps(sort_keys=True, separators=(",", ":"))`). `verify_snapshot()`
  recomputes and compares. Any mutation invalidates it.

---

## 6. Transport (`sync.py`)

Order: HTTPS first, SSH-drop fallback (`sync_snapshot()` returns
`{transport, detail}`).

- `post_snapshot(payload, server_url, timeout=10)`: POST to
  `<server>/api/v1/ingest`, parses the reply as JSON and requires
  `{"ok": true}` — anything else raises. **Why:** the LDAP proxy 302-redirects
  anonymous POSTs to an HTML login page (urllib follows it); accepting that as
  success would silently drop data.
- `ssh_drop_snapshot(payload, ssh_host="own3", remote_dir, timeout=30)`:
  filename `<safe-user>-<UTC-timestamp>.json`, bytes piped via
  `ssh <host> "cat > <remote_path>"` stdin (no shell-quoting issues). Raises on
  non-zero exit with stderr excerpt.
- Defaults overridable by env: `AGENT_TOKENS_SERVER`
  (`https://token-leaderboard.own3.aganitha.ai`), `AGENT_TOKENS_SSH_HOST`
  (`own3`), `AGENT_TOKENS_REMOTE_DIR`
  (`/shared/hriteek/token-leaderboard/dropbox`); `AGENT_TOKENS_NO_SYNC=1`
  disables.

---

## 7. Server (`server/app.py`, stdlib only)

Single file, `http.server.ThreadingHTTPServer` + `sqlite3`, no pip deps.
Env: `DATA_DIR` (default `/data`, shared), `DB_DIR` (default = `DATA_DIR`;
production: container-local volume), `PORT` (default `8734`),
`INGEST_TOKEN` (default empty = open), `LEADERBOARD_TTL_S` (default 5).
Shared files: `ledger.jsonl`, `dropbox/`, `processed/`, `users.json`
(admin `{username: role}` overrides).

### 7.1 Endpoints

| Method | Path | Behavior |
|---|---|---|
| POST | `/api/v1/ingest?owner=` | Parse ≤2MB JSON → `ingest_snapshot(payload, owner_hint)`. 202 + `{"ok": true, "id"}` (or `"deduped": true`); 403 when `INGEST_TOKEN` is set and the request lacks it (`?token=` or `X-Ingest-Token`); 400 on bad schema/checksum/values; 413 over limit; 404 otherwise |
| GET | `/api/v1/leaderboard?window=daily\|weekly` | §7.3 JSON (unknown window → daily) |
| GET | `/api/v1/health` | `{"ok": true}` |
| GET | `/`, `/index.html` | `dashboard.html` (`text/html`) |
| GET | `/logo.png` | vendored org logo (`image/png`, 1-day cache) |

CORS `*`; OPTIONS handled.

### 7.2 Ingest validation (`ingest_snapshot`)

Rejects with `ValueError` unless ALL hold:

1. `schema == "agent-tokens.snapshot/v1"`; checksum verifies.
2. Username `^[a-z0-9._-]{1,64}$` (lowercased); `owner_hint` (SSH UID) wins.
3. All rendered names (role, host, agent, model) match `^[A-Za-z0-9._\-/ ()]{1,128}$`.
4. Role: `users.json[username]` wins over client value.
5. `collected_at` within `[now−30d, now+5m]`; `0 <= every total <= 10**13`.
6. Checksum dedupe: known checksum → `{ok, id, deduped: True}`.
7. Append row; mirror to `ledger.jsonl` unless `mirror_ledger=False` (replay).

SQLite DDL (lives in `DB_DIR`, default = `DATA_DIR`; production mounts a
container-local volume because SQLite locking is unreliable on NFS — see §10):

```sql
CREATE TABLE snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL, email TEXT NOT NULL DEFAULT '',
  role TEXT NOT NULL DEFAULT 'other', host TEXT NOT NULL DEFAULT '',
  client_version TEXT NOT NULL DEFAULT '',
  collected_at TEXT NOT NULL, total_tokens INTEGER NOT NULL DEFAULT 0,
  checksum TEXT NOT NULL DEFAULT '',
  agents_json TEXT NOT NULL DEFAULT '[]',
  models_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL);
CREATE INDEX idx_snap_user_time ON snapshots(username, collected_at);
CREATE INDEX idx_snap_checksum ON snapshots(checksum);
```

### 7.3 Leaderboard algorithm

Local counters are **cumulative**, so windows are computed as deltas over
**per-(user, host) series** (a fresh laptop can never zero another machine's
score; multi-machine users sum correctly):

- `window_start`: daily = today 00:00 UTC; weekly = Monday 00:00 UTC.
- Per series: `baseline` = latest snapshot strictly before window start (plus
  its per-model/per-agent maps); `in_window` = snapshots at/after start.
  Series with no in-window snapshots are skipped.
- `score = Σ max(0, latest_total − baseline_total)` across the user's series
  (baseline 0 for brand-new series — onboarding day counts the full total).
  Same delta math per harness (`agents_json`) and per model (`models_json`,
  keyed `agent/model`, top 25 returned).
- Response: `{window, window_start, generated_at, users[] (rank, username, role,
  email, tokens, cumulative, pushes, last_push), by_role{}, roles[], harnesses[],
  models[]}` with users sorted desc, ranks assigned. Results are cached
  (`LEADERBOARD_TTL_S`, default 5s; key includes the DB path) and the cache is
  invalidated on every ingest.

### 7.4 Dropbox poller

Background thread every 5s (`poll_dropbox_once`): for each `*.json`, parse;
on parse failure move to `processed/<name>.bad`; else
`ingest_snapshot(payload, owner_hint=owner_of(file))` where `owner_of` resolves
the file's UID via `pwd` (the SSH login — the anti-spoof anchor), then unlink.
Ingest errors → `processed/<name>.err` + unlink (poison files never block).

---

## 8. Permissions (`scripts/setup_shared_dir.sh`)

Target: `/shared/hriteek/token-leaderboard` (override path via `$1`). No sudo
needed when the admin owns the parent.

| Path | Mode | Meaning |
|---|---|---|
| `dropbox/` | `1733` (sticky, create-only) | anyone can `ssh host "cat > dropbox/…"`; nobody can list, read, overwrite, or delete others' files |
| `processed/` | `700` | server only (`.bad`/`.err` quarantine) |
| `ledger.jsonl` | `600` | append-only source of truth; SQLite is rebuilt from it |
| `users.json` | `644`, default `{}` | admin-curated LDAP-group → role map |

Why the server runs as **root** (documented in `server/Dockerfile`): only root
(or the dir owner) can list/read/unlink all files in a 1733 directory — a
non-root server user would be blind to submissions. The trust boundary is the
LDAP-gated proxy + labels, not the container uid.

Anti-cheat summary: attribution = filesystem UID (SSH) or admin map, never the
JSON body; machine HTTPS ingest additionally requires `INGEST_TOKEN`
(`server/.env`, gitignored, set once per host — direct container-IP POSTs that
bypass the LDAP proxy get 403); raw drops are consumed once then deleted;
history is append-only;
self-inflation of one's *own* counters is detectable (ledger holds checksums,
hosts, timestamps) but not preventable — treat the board as motivational, not
payroll-grade. See `PROS_CONS.md`.

---

## 9. Dashboard (`server/dashboard.html`)

Single file, no build step, 10s auto-refresh. Layout: header (logo + title +
Daily/Weekly tabs) → overall leaderboard + harness/model side tables → role-wise
board with role selector → footer.

- Palette (flat, no gradients — benchmark-chart style): page `#f1f3f4`, cards
  `#ffffff`, hairlines `#e5e7eb`, ink `#111827`, muted `#6b7280`, accent Google
  blue `#1a73e8` (+ wash `#e8f0fe`), bars slate `#9ca3af` (leader blue),
  best-cells `#eef0f3`. Rank-1 row: blue wash + 3px blue left edge.
- Tabs refetch `/api/v1/leaderboard?window=`; scope pill shows the real range
  (`today · Sep 4` / `this week · Aug 31 → Sep 4`, from `window_start`).
- Number format: `2.50M / 450.0K / 1,234`. Token fields: `tokens` (window),
  plus `cumulative` on the role board.
- Branding: `server/logo.png` (vendored org mark, 158×40 transparent PNG).

---

## 10. Docker + reverse-proxy deploy

own3 convention (verified against viv-dashboard, pKa, scd-dossier): **no `ports:`**
**mapping — strictly prohibited.** The host proxy auto-serves
`https://<container_name>.own3.aganitha.ai`, routing to the labeled internal
port. Required compose shape:

```yaml
name: token-leaderboard
services:
  board:
    build: {context: <repo root>, dockerfile: server/Dockerfile}
    container_name: token-leaderboard   # = public subdomain
    restart: unless-stopped
    environment: [DATA_DIR=/data, DB_DIR=/dbdata, PORT=8734,
                  INGEST_TOKEN=${INGEST_TOKEN:-}, LEADERBOARD_TTL_S=5]
    volumes: [/shared/hriteek/token-leaderboard:/data,
              token-board-db:/dbdata]   # named local volume for the DB
    labels: {user: "hriteek",
             description: "Aganitha agent token-maxing leaderboard",
             port: "8734", security: "ldap"}
```

`Dockerfile`: `python:3.11-slim`, copy `app.py` + `dashboard.html` + `logo.png`,
`EXPOSE 8734`, `CMD ["python3", "app.py"]` (runs as root per §8).

Deploy (own3, repo root): `bash scripts/setup_shared_dir.sh`, create
`server/.env` with `INGEST_TOKEN=<random 32 bytes>` (`chmod 600`, never
committed), then `docker compose -f server/docker-compose.yml up -d --build`. Verify:
`docker exec token-leaderboard` → `GET 127.0.0.1:8734/api/v1/health` is
`{"ok": true}`; public URL 302-redirects to LDAP login when anonymous (correct).

---

## 11. User + admin flows

**New user (per machine):** clone → `bash scripts/install.sh` →
`agent-tokens --onboard --email <name@aganitha.ai> --role <role>` →
`agent-tokens doctor` (no FAIL) → use `agent-tokens` normally. First push
appears on the board within seconds via the SSH drop.

**Admin:** run `setup_shared_dir.sh` once; keep `users.json` in sync with LDAP
groups (`ldap_group_to_role` mapping); read incidents from `ledger.jsonl`
(checksums/hosts/timestamps); redeploy via compose. Test rows or poison data:
stop container, delete/adjust SQLite rows (keep `ledger.jsonl*` backups for
audit), restart.

---

## 12. Tests (stdlib `unittest`, `python3 -m unittest discover tests`)

`test_cli.py` (registry, dispatch, failure isolation — never syncs: kill-switch
is forced in `setUp`); `test_org.py` (identity, snapshot tamper-reject, HTTPS→SSH
fallback, login-HTML + XSS + timestamp rejection, owner-hint/role-override,
dedupe, daily/weekly + multi-host deltas, token gate, ledger replay, doctor);
`test_formatters.py` + provider suites (formatting, zero-row hiding, fixtures).
