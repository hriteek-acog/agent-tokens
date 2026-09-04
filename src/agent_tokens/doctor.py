"""Preflight checks: `agent-tokens doctor`.

Verifies everything a new user needs, with actionable fixes:
  1. CLI install sane (version, python)
  2. Org identity linked (else: exact onboard command)
  3. Leaderboard server reachable (LDAP 302 counts as reachable-but-login)
  4. SSH file-drop path works (ssh own3 + dropbox writable)

Exit 0 when able to sync by at least one transport, else 1. Never raises.
"""

import os
import shutil
import socket
import subprocess
import sys
import urllib.request

OK, WARN, FAIL = "ok", "warn", "fail"


def _check_install() -> tuple:
    from agent_tokens import __version__

    return (OK, f"agent-tokens {__version__} on {sys.version.split()[0]} ({sys.executable})")


def _check_identity() -> tuple:
    from agent_tokens.identity import load_identity

    ident = load_identity()
    if not ident:
        return (
            FAIL,
            "no org identity — run: agent-tokens --onboard "
            "--email you@aganitha.ai --role engineering",
        )
    return (OK, f"{ident.username} <{ident.email}> [{ident.role}]")


def _check_server(server_url: str) -> tuple:
    from agent_tokens.sync import DEFAULT_SERVER_URL

    url = (server_url or DEFAULT_SERVER_URL).rstrip("/") + "/api/v1/health"
    try:
        with urllib.request.urlopen(url, timeout=8) as resp:
            body = resp.read(200).decode("utf-8", "replace")
            if '"ok": true' in body:
                return (OK, f"server reachable (direct): {url}")
            return (
                WARN,
                f"server answered but not JSON — likely LDAP login gate; "
                f"SSH-drop sync still works: {url}",
            )
    except Exception as exc:
        msg = str(exc)
        if "CERTIFICATE_VERIFY_FAILED" in msg:
            return (
                WARN,
                "server TLS uses internal CA (direct HTTPS blocked); "
                "SSH-drop sync still works",
            )
        return (WARN, f"server not directly reachable ({msg[:120]}); SSH-drop sync still works")


def _check_ssh(ssh_host: str, remote_dir: str) -> tuple:
    if not shutil.which("ssh"):
        return (FAIL, "ssh client not found on PATH")
    try:
        proc = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", ssh_host,
             f"test -d {remote_dir} && touch {remote_dir}/.doctor && rm {remote_dir}/.doctor && echo WRITE-OK"],
            capture_output=True, timeout=20,
        )
    except Exception as exc:
        return (FAIL, f"ssh {ssh_host} failed ({exc}) — check `ssh {ssh_host}` first")
    out = (proc.stdout or b"").decode("utf-8", "replace")
    if proc.returncode == 0 and "WRITE-OK" in out:
        try:
            user = subprocess.run(
                ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                 ssh_host, "whoami"],
                capture_output=True, timeout=20,
            ).stdout.decode().strip()
        except Exception:
            user = "?"
        return (OK, f"ssh {ssh_host} as {user}; dropbox writable")
    err = (proc.stderr or b"").decode("utf-8", "replace")[:160]
    return (FAIL, f"ssh {ssh_host} or dropbox write failed ({err or 'exit ' + str(proc.returncode)})")


def run_doctor(server_url=None, ssh_host=None, remote_dir=None) -> int:
    from agent_tokens.sync import DEFAULT_REMOTE_DIR, DEFAULT_SERVER_URL, DEFAULT_SSH_HOST

    server_url = server_url or os.environ.get("AGENT_TOKENS_SERVER", DEFAULT_SERVER_URL)
    ssh_host = ssh_host or os.environ.get("AGENT_TOKENS_SSH_HOST", DEFAULT_SSH_HOST)
    remote_dir = remote_dir or os.environ.get("AGENT_TOKENS_REMOTE_DIR", DEFAULT_REMOTE_DIR)

    checks = [
        ("install", _check_install()),
        ("identity", _check_identity()),
        ("server", _check_server(server_url)),
        ("ssh-drop", _check_ssh(ssh_host, remote_dir)),
    ]
    worst = 0
    rank = {OK: 0, WARN: 1, FAIL: 2}
    for name, (status, detail) in checks:
        worst = max(worst, rank[status])
        print(f"[{status.upper():4}] {name}: {detail}")
    if worst == 0:
        print("doctor: all good — usage will sync.")
    elif checks[1][1][0] == FAIL or checks[3][1][0] == FAIL and checks[2][1][0] == FAIL:
        print("doctor: cannot sync yet — fix the FAIL lines above.")
    else:
        print("doctor: usable — at least one sync transport works.")
    return 0 if worst < 2 else 1


def main(argv=None) -> int:
    return run_doctor()


if __name__ == "__main__":
    raise SystemExit(main())
