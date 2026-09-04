"""Org sync: build a signed snapshot and push it to the leaderboard server.

Primary transport is HTTPS POST to the FastAPI/std-lib server
(POST /api/v1/ingest) — the server ingests instantly into SQLite and the
dashboard reflects it on next poll (2s refresh).

Fallback transport is SSH file-drop to own3:
  ssh own3 "cat > /shared/hriteek/token-leaderboard/dropbox/<user>-<ts>.json"
The server's dropbox watcher ingests files by filesystem UID owner, so the
username is taken from the SSH login, not from the JSON body — hand-editing
another user's file is blocked by sticky-bit perms (see scripts/).

Every snapshot carries a sha256 checksum over its canonical JSON so the
server can reject truncated/tampered bodies. This is tamper-EVIDENT, not
tamper-PROOF against the file owner inflating their own numbers — the LDAP
cross-check + append-only ledger + anomaly flags (docs/PROS_CONS.md) are the
backstop. Nobody can edit another user's data or rewrite history.
"""

import datetime as _dt
import hashlib
import json
import os
import socket
import subprocess
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_SERVER_URL = os.environ.get(
    "AGENT_TOKENS_SERVER", "https://token-leaderboard.own3.aganitha.ai"
)
DEFAULT_SSH_HOST = os.environ.get("AGENT_TOKENS_SSH_HOST", "own3")
DEFAULT_REMOTE_DIR = os.environ.get(
    "AGENT_TOKENS_REMOTE_DIR", "/shared/hriteek/token-leaderboard/dropbox"
)


def utc_now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def checksum_of(payload: Dict[str, Any]) -> str:
    body = {k: v for k, v in payload.items() if k != "checksum"}
    return hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()


def build_snapshot(
    username: str,
    email: str,
    role: str,
    reports: List[Any],
    client_version: str = "",
) -> Dict[str, Any]:
    """Collapse per-agent reports into one snapshot dict (JSON-serialisable)."""
    agents: List[Dict[str, Any]] = []
    models: List[Dict[str, Any]] = []
    total = 0
    for rep in reports or []:
        if rep is None:
            continue
        agent_total = 0
        for m in getattr(rep, "models", []) or []:
            mt = m.total_tokens  # single formula lives on TokenStats
            agent_total += mt
            models.append(
                {
                    "agent_name": getattr(rep, "agent_name", "unknown"),
                    "model_id": m.model_id,
                    "total_tokens": mt,
                    "session_count": m.session_count or 0,
                    "turn_count": m.turn_count or 0,
                }
            )
        total += agent_total
        agents.append(
            {"agent_name": getattr(rep, "agent_name", "unknown"), "total_tokens": agent_total}
        )
    payload: Dict[str, Any] = {
        "schema": "agent-tokens.snapshot/v1",
        "username": username,
        "email": email,
        "role": role,
        "host": socket.gethostname(),
        "client_version": client_version,
        "collected_at": utc_now_iso(),
        "total_tokens": total,
        "agents": agents,
        "models": models,
    }
    payload["checksum"] = checksum_of(payload)
    return payload


def verify_snapshot(payload: Dict[str, Any]) -> bool:
    expect = payload.get("checksum")
    if not expect:
        return False
    return checksum_of(payload) == expect


def post_snapshot(
    payload: Dict[str, Any],
    server_url: str = DEFAULT_SERVER_URL,
    timeout_s: int = 10,
) -> str:
    """POST snapshot to server. Returns server response text. Raises on failure.

    The own3 reverse proxy sits in front of the server with LDAP auth: an
    unauthenticated POST is 302-redirected to the login page (HTML). That must
    NOT count as success — so the response is required to be JSON with
    ``{"ok": true}``; anything else raises and the caller falls back to the
    SSH file-drop, which bypasses the proxy entirely.
    """
    url = server_url.rstrip("/") + "/api/v1/ingest"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        raw = resp.read().decode("utf-8", "replace")
    try:
        parsed = json.loads(raw)
    except ValueError:
        raise RuntimeError(
            "server did not accept snapshot (non-JSON reply — likely auth redirect)"
        )
    if not isinstance(parsed, dict) or parsed.get("ok") is not True:
        raise RuntimeError(f"server rejected snapshot: {raw[:200]}")
    return raw


def ssh_drop_snapshot(
    payload: Dict[str, Any],
    ssh_host: str = DEFAULT_SSH_HOST,
    remote_dir: str = DEFAULT_REMOTE_DIR,
    timeout_s: int = 30,
) -> str:
    """Write snapshot via `ssh <host> 'cat > dropbox/<user>-<ts>.json'`.

    The remote filename is derived from the payload username + timestamp; the
    server additionally prefers the file's UID owner over the JSON username.
    Returns the remote path written.
    """
    safe_user = "".join(c if (c.isalnum() or c in "._-") else "-" for c in payload["username"])
    ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    remote_path = f"{remote_dir}/{safe_user}-{ts}.json"
    blob = json.dumps(payload)
    # Pass via stdin to avoid shell-quoting issues.
    cmd = ["ssh", ssh_host, f"cat > {remote_path}"]
    proc = subprocess.run(
        cmd, input=blob.encode("utf-8"), capture_output=True, timeout=timeout_s
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ssh drop failed: {proc.stderr.decode('utf-8', 'replace')[:500]}")
    return remote_path


def sync_snapshot(
    payload: Dict[str, Any],
    server_url: str = DEFAULT_SERVER_URL,
    ssh_host: Optional[str] = DEFAULT_SSH_HOST,
    try_ssh_fallback: bool = True,
) -> Dict[str, str]:
    """Try HTTPS first (instant), fall back to SSH drop (offline-friendly)."""
    try:
        resp = post_snapshot(payload, server_url=server_url)
        return {"transport": "https", "detail": resp[:300]}
    except Exception as exc:
        https_err = str(exc)[:300]
        if not (try_ssh_fallback and ssh_host):
            raise RuntimeError(f"https ingest failed and no fallback: {https_err}")
        remote = ssh_drop_snapshot(payload, ssh_host=ssh_host)
        return {"transport": "ssh-drop", "detail": f"{remote} (https failed: {https_err})"}
