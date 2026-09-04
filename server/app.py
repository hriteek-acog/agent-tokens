"""Leaderboard server (stdlib only — no pip dependencies).

Endpoints:
  POST /api/v1/ingest?owner=<ssh-user>   JSON snapshot from sync.py
  GET  /api/v1/leaderboard?window=daily|weekly
  GET  /api/v1/health
  GET  /                               dashboard UI (single file)

Storage:
  DATA_DIR (default /data):
    leaderboard.db   SQLite — snapshots ledger (append-only)
    ledger.jsonl     raw JSONL mirror (audit trail)
    dropbox/         SSH file-drop inbox (polled every 5s)
    users.json       optional admin override {username: role}

Scoring (cumulative counters -> window deltas):
  Local providers report cumulative all-time totals, so the server converts
  to window usage: score(user, window) = latest_total_in_window -
  baseline_total, where baseline = latest snapshot strictly before the window
  starts. A brand-new user with no baseline is scored against 0 (their whole
  total counts on onboarding day). Same delta logic applies per harness
  (agent) and per model.

Security model:
  * HTTPS ingest trusts the JSON username only as a hint; SSH-dropbox ingest
    prefers the file's UID owner (pwd lookup) — the ssh login — over the body.
  * users.json (root-managed, from LDAP groups) overrides client-declared role.
  * DB + ledger live outside the dropbox and are writable only by the server
    UID; dropbox is mode 1733 (write-only + sticky) so users can create but
    neither read nor modify each other's files, and files are moved to
    processed/ after ingest (replay-safe via checksum dedupe).
"""

import hashlib
import html
import json
import os
import pwd
import sqlite3
import threading
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
DB_PATH = DATA_DIR / "leaderboard.db"
LEDGER_PATH = DATA_DIR / "ledger.jsonl"
DROPBOX = DATA_DIR / "dropbox"
PROCESSED = DATA_DIR / "processed"
USERS_JSON = DATA_DIR / "users.json"
HERE = Path(__file__).resolve().parent

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL,
  email TEXT NOT NULL DEFAULT '',
  role TEXT NOT NULL DEFAULT 'other',
  host TEXT NOT NULL DEFAULT '',
  client_version TEXT NOT NULL DEFAULT '',
  collected_at TEXT NOT NULL,
  total_tokens INTEGER NOT NULL DEFAULT 0,
  checksum TEXT NOT NULL DEFAULT '',
  agents_json TEXT NOT NULL DEFAULT '[]',
  models_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snap_user_time ON snapshots(username, collected_at);
CREATE INDEX IF NOT EXISTS idx_snap_checksum ON snapshots(checksum);
"""


def db() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_ts(s: str) -> datetime:
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d
    except Exception:
        return utcnow()


def canonical(payload: dict) -> str:
    body = {k: v for k, v in payload.items() if k != "checksum"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"))


def verify(payload: dict) -> bool:
    expect = payload.get("checksum")
    if not expect:
        return False
    return hashlib.sha256(canonical(payload).encode()).hexdigest() == expect


def role_overrides() -> dict:
    try:
        return json.loads(USERS_JSON.read_text())
    except Exception:
        return {}


def ingest_snapshot(payload: dict, owner_hint: str = "") -> dict:
    """Validate + append. Returns {'ok': True, 'id': N} or raises ValueError."""
    if not isinstance(payload, dict) or payload.get("schema") != "agent-tokens.snapshot/v1":
        raise ValueError("unknown snapshot schema")
    if not verify(payload):
        raise ValueError("checksum mismatch (truncated or tampered body)")
    username = str(payload.get("username", "")).strip().lower()
    if owner_hint:
        username = owner_hint.strip().lower()  # SSH UID wins over body
    if not username or len(username) > 64:
        raise ValueError("bad username")
    overrides = role_overrides()
    role = str(overrides.get(username, payload.get("role", "other"))).lower()
    collected = parse_ts(payload.get("collected_at", ""))
    total = int(payload.get("total_tokens", 0) or 0)
    if total < 0 or total > 10**13:
        raise ValueError("implausible total_tokens")

    conn = db()
    try:
        dup = conn.execute(
            "SELECT id FROM snapshots WHERE checksum=?", (payload.get("checksum"),)
        ).fetchone()
        if dup:
            return {"ok": True, "id": dup["id"], "deduped": True}
        cur = conn.execute(
            "INSERT INTO snapshots (username,email,role,host,client_version,"
            " collected_at,total_tokens,checksum,agents_json,models_json,created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                username, str(payload.get("email", "")), role,
                str(payload.get("host", "")), str(payload.get("client_version", "")),
                collected.isoformat(), total, str(payload.get("checksum", "")),
                json.dumps(payload.get("agents", [])), json.dumps(payload.get("models", [])),
                utcnow().isoformat(),
            ),
        )
        conn.commit()
        snap_id = cur.lastrowid
    finally:
        conn.close()
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(LEDGER_PATH, "a") as fh:
            fh.write(json.dumps({**payload, "username": username, "role": role}) + "\n")
    except OSError:
        pass
    return {"ok": True, "id": snap_id}


def window_start(window: str, now: datetime) -> datetime:
    if window == "weekly":
        monday = (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return monday
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def leaderboard(window: str = "daily") -> dict:
    now = utcnow()
    start = window_start(window, now)
    conn = db()
    try:
        rows = conn.execute(
            "SELECT username,email,role,host,collected_at,total_tokens,"
            " agents_json,models_json FROM snapshots ORDER BY collected_at ASC"
        ).fetchall()
    finally:
        conn.close()

    per_user: dict = {}
    for r in rows:
        per_user.setdefault(r["username"], []).append(dict(r))

    users, harness_tot, model_tot, role_tot = [], {}, {}, {}
    for username, snaps in per_user.items():
        snaps.sort(key=lambda s: s["collected_at"])
        base = None
        base_models: dict = {}
        base_agents: dict = {}
        for s in snaps:
            if parse_ts(s["collected_at"]) < start:
                base = s
                base_models = {(m.get("agent_name"), m.get("model_id")): m.get("total_tokens", 0)
                               for m in _loads(s["models_json"])}
                base_agents = {a.get("agent_name"): a.get("total_tokens", 0)
                               for a in _loads(s["agents_json"])}
        in_window = [s for s in snaps if parse_ts(s["collected_at"]) >= start]
        if not in_window:
            continue
        latest = in_window[-1]
        base_total = base["total_tokens"] if base else 0
        score = max(0, latest["total_tokens"] - base_total)
        role = latest["role"]
        users.append({
            "username": username, "role": role,
            "email": latest["email"], "host": latest["host"],
            "tokens": score,
            "cumulative": latest["total_tokens"],
            "pushes": len(in_window),
            "last_push": latest["collected_at"],
        })
        role_tot[role] = role_tot.get(role, 0) + score
        for m in _loads(latest["models_json"]):
            key = f"{m.get('agent_name')}/{m.get('model_id')}"
            prev = base_models.get((m.get("agent_name"), m.get("model_id")), 0) if base else 0
            d = max(0, m.get("total_tokens", 0) - prev)
            entry = model_tot.setdefault(key, {"tokens": 0, "sessions": 0})
            entry["tokens"] += d
            entry["sessions"] += m.get("session_count", 0) or 0
        for a in _loads(latest["agents_json"]):
            prev = base_agents.get(a.get("agent_name"), 0) if base else 0
            harness_tot[a.get("agent_name")] = harness_tot.get(a.get("agent_name"), 0) + max(
                0, a.get("total_tokens", 0) - prev)

    users.sort(key=lambda u: u["tokens"], reverse=True)
    for i, u in enumerate(users, 1):
        u["rank"] = i
    by_role: dict = {}
    for u in users:
        by_role.setdefault(u["role"], []).append(u)
    return {
        "window": window,
        "window_start": start.isoformat(),
        "generated_at": now.isoformat(),
        "users": users,
        "by_role": by_role,
        "roles": sorted(
            [{"role": k, "tokens": v} for k, v in role_tot.items()],
            key=lambda r: r["tokens"], reverse=True),
        "harnesses": sorted(
            [{"harness": k, "tokens": v} for k, v in harness_tot.items()],
            key=lambda r: r["tokens"], reverse=True),
        "models": sorted(
            [{"model": k, **v} for k, v in model_tot.items()],
            key=lambda r: r["tokens"], reverse=True)[:25],
    }


def _loads(s) -> list:
    try:
        v = json.loads(s or "[]")
        return v if isinstance(v, list) else []
    except Exception:
        return []


def owner_of(path: Path) -> str:
    try:
        return pwd.getpwuid(path.stat().st_uid).pw_name.lower()
    except Exception:
        return ""


def poll_dropbox_once() -> int:
    DROPBOX.mkdir(parents=True, exist_ok=True)
    PROCESSED.mkdir(parents=True, exist_ok=True)
    n = 0
    for f in sorted(DROPBOX.glob("*.json")):
        try:
            payload = json.loads(f.read_text())
        except Exception:
            (PROCESSED / (f.name + ".bad")).write_bytes(f.read_bytes())
            f.unlink(missing_ok=True)
            continue
        try:
            ingest_snapshot(payload, owner_hint=owner_of(f))
            n += 1
            f.unlink(missing_ok=True)
        except Exception as exc:
            (PROCESSED / (f.name + ".err")).write_text(
                json.dumps({"error": str(exc)[:300], "file": f.name}))
            f.unlink(missing_ok=True)
    return n


def dropbox_loop(stop: threading.Event, interval_s: int = 5) -> None:
    while not stop.is_set():
        try:
            poll_dropbox_once()
        except Exception:
            pass
        stop.wait(interval_s)


class Handler(BaseHTTPRequestHandler):
    server_version = "token-board/1.0"

    def log_message(self, *a):
        pass

    def _send(self, code: int, body: bytes, ctype: str = "application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        if parsed.path == "/api/v1/health":
            self._send(200, b'{"ok": true}')
        elif parsed.path == "/api/v1/leaderboard":
            window = (qs.get("window", ["daily"])[0] or "daily").lower()
            if window not in ("daily", "weekly"):
                window = "daily"
            self._send(200, json.dumps(leaderboard(window)).encode())
        elif parsed.path in ("/", "/index.html"):
            page = (HERE / "dashboard.html").read_text()
            self._send(200, page.encode(), "text/html; charset=utf-8")
        elif parsed.path == "/logo.png":
            try:
                blob = (HERE / "logo.png").read_bytes()
            except OSError:
                return self._send(404, b'{"error": "not found"}')
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(blob)))
            self.send_header("Cache-Control", "public, max-age=86400")
            self.end_headers()
            self.wfile.write(blob)
        else:
            self._send(404, b'{"error": "not found"}')

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/api/v1/ingest":
            return self._send(404, b'{"error": "not found"}')
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length > 2_000_000:
            return self._send(413, b'{"error": "payload too large"}')
        try:
            payload = json.loads(self.rfile.read(length or 0) or b"{}")
        except Exception:
            return self._send(400, b'{"error": "invalid json"}')
        qs = urllib.parse.parse_qs(parsed.query)
        owner = (qs.get("owner", [""])[0] or "")
        try:
            result = ingest_snapshot(payload, owner_hint=owner)
            self._send(202, json.dumps(result).encode())
        except ValueError as exc:
            self._send(400, json.dumps(
                {"error": html.escape(str(exc)[:300])}).encode())


def main() -> None:
    port = int(os.environ.get("PORT", "8734"))
    stop = threading.Event()
    threading.Thread(target=dropbox_loop, args=(stop,), daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
