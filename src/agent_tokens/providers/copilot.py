"""Provider for GitHub Copilot (CLI harness + VSCode chat extension)."""

import glob
import json
import os
import sqlite3
from typing import Dict, List, Optional

from agent_tokens.models import AgentReport, TokenStats, SessionInfo
from agent_tokens.providers._util import (
    connect_ro,
    file_is_today,
    is_today_str,
    parse_iso_to_local,
    safe_int,
)
from agent_tokens.providers.base import BaseProvider

_CHAT_MODEL = "copilot-chat"


def _parse_harness_events(path: str) -> Optional[Dict[str, object]]:
    """Parse one ``~/.copilot/session-state/<id>/events.jsonl`` harness log.

    Returns model, turn count, estimated tokens (``session.shutdown``
    ``currentTokens`` — Copilot exposes no local input/output split, so the
    estimate is recorded as input) and timestamps. ``None`` when the log
    carries no usable session.
    """
    model: Optional[str] = None
    turns = 0
    current_tokens = 0
    start: Optional[str] = None
    end: Optional[str] = None
    cwd: Optional[str] = None
    repo: Optional[str] = None
    seen_start = False
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                rtype = rec.get("type")
                data = rec.get("data", {})
                if not isinstance(data, dict):
                    continue
                if rtype == "session.start":
                    seen_start = True
                    model = data.get("selectedModel") or model
                    start = data.get("startTime") or start
                    ctx = data.get("context", {})
                    if isinstance(ctx, dict):
                        cwd = ctx.get("cwd") or cwd
                        repo = ctx.get("repository") or repo
                elif rtype == "session.resume":
                    model = data.get("selectedModel") or model
                elif rtype == "session.model_change":
                    model = data.get("newModel") or model
                elif rtype == "assistant.turn_end":
                    turns += 1
                elif rtype == "session.shutdown":
                    current_tokens = safe_int(data.get("currentTokens"), current_tokens)
                    end = rec.get("timestamp") or end
    except OSError:
        return None
    if not seen_start:
        return None
    return {
        "model": model or _CHAT_MODEL,
        "turns": turns,
        "tokens": current_tokens,
        "start": start,
        "end": end,
        "cwd": cwd,
        "repo": repo,
    }


class CopilotProvider(BaseProvider):
    """Reads Copilot CLI harness logs and the VSCode chat session store.

    Token figures are estimates: the harness only reports a ``currentTokens``
    context size at shutdown (recorded as input; no output split exists
    locally), and the chat extension store exposes sessions/turns without
    token counts at all.
    """

    def __init__(
        self,
        harness_dir: Optional[str] = None,
        chat_db: Optional[str] = None,
    ):
        self.harness_dir = harness_dir or os.path.expanduser("~/.copilot/session-state")
        self.chat_db = chat_db or os.path.expanduser(
            "~/Library/Application Support/Code/User/globalStorage/"
            "github.copilot-chat/session-store.db"
        )

    @property
    def name(self) -> str:
        return "Copilot"

    def is_available(self) -> bool:
        return os.path.isdir(self.harness_dir) or os.path.exists(self.chat_db)

    def _harness_sessions(self, today_only: bool) -> List[Dict[str, object]]:
        out = []
        if not os.path.isdir(self.harness_dir):
            return out
        for path in sorted(
            glob.glob(os.path.join(self.harness_dir, "*", "events.jsonl"))
        ):
            parsed = _parse_harness_events(path)
            if not parsed:
                continue
            stamp = parsed.get("end") or parsed.get("start")
            if today_only and not (is_today_str(stamp) or file_is_today(path)):
                continue
            parsed["path"] = path
            out.append(parsed)
        return out

    def _chat_sessions(self, today_only: bool) -> List[Dict[str, object]]:
        out = []
        if not os.path.exists(self.chat_db):
            return out
        try:
            with connect_ro(self.chat_db) as conn:
                cur = conn.cursor()
                try:
                    cur.execute(
                        "SELECT id, cwd, repository, summary, agent_name,"
                        " created_at, updated_at FROM sessions"
                    )
                except sqlite3.Error:
                    return out
                rows = cur.fetchall()
                turn_counts: Dict[str, int] = {}
                try:
                    for r in cur.execute(
                        "SELECT session_id, COUNT(*) FROM turns GROUP BY session_id"
                    ):
                        turn_counts[r[0]] = safe_int(r[1])
                except sqlite3.Error:
                    pass
        except (sqlite3.Error, OSError):
            return out
        for r in rows:
            stamp = r["updated_at"] or r["created_at"]
            if today_only and not is_today_str(stamp):
                continue
            out.append(
                {
                    "id": r["id"],
                    "cwd": r["cwd"],
                    "repo": r["repository"],
                    "summary": r["summary"],
                    "agent": r["agent_name"],
                    "turns": turn_counts.get(r["id"], 0),
                    "stamp": stamp,
                }
            )
        return out

    def get_report(self, today_only: bool = False) -> Optional[AgentReport]:
        if not self.is_available():
            return None

        models: Dict[str, Dict[str, object]] = {}
        sessions: List[SessionInfo] = []
        seen_ids = set()

        def bucket(mid: str) -> Dict[str, object]:
            return models.setdefault(
                mid,
                {"input": 0, "output": 0, "turns": 0, "sessions": set(), "last": ""},
            )

        for h in self._harness_sessions(today_only):
            mid = str(h.get("model") or _CHAT_MODEL)
            b = bucket(mid)
            b["input"] = safe_int(b["input"]) + safe_int(h.get("tokens"))
            b["turns"] = safe_int(b["turns"]) + safe_int(h.get("turns"))
            b["sessions"].add(os.path.basename(os.path.dirname(str(h.get("path", "")))))
            local = parse_iso_to_local(h.get("end") or h.get("start"))
            if local and local > str(b["last"]):
                b["last"] = local
            sid = os.path.basename(os.path.dirname(str(h.get("path", ""))))
            seen_ids.add(sid)
            title = str(h.get("repo") or "") or os.path.basename(str(h.get("cwd") or "").rstrip("/")) or sid[:18]
            sessions.append(
                SessionInfo(
                    session_id=sid,
                    title=title,
                    model_id=mid,
                    input_tokens=safe_int(h.get("tokens")),
                    turn_count=safe_int(h.get("turns")),
                    updated_at=local,
                )
            )

        for c in self._chat_sessions(today_only):
            sid = str(c["id"])
            if sid in seen_ids:
                continue
            seen_ids.add(sid)
            mid = str(c.get("agent") or _CHAT_MODEL)
            b = bucket(mid)
            b["turns"] = safe_int(b["turns"]) + safe_int(c.get("turns"))
            b["sessions"].add(sid)
            local = parse_iso_to_local(c.get("stamp"))
            if local and local > str(b["last"]):
                b["last"] = local
            title = str(c.get("summary") or "")[:60] or (str(c.get("repo") or "") or os.path.basename(str(c.get("cwd") or "").rstrip("/")) or sid[:18])
            sessions.append(
                SessionInfo(
                    session_id=sid,
                    title=title,
                    model_id=mid,
                    turn_count=safe_int(c.get("turns")),
                    updated_at=local,
                )
            )

        stats = [
            TokenStats(
                model_id=m,
                input_tokens=safe_int(b["input"]),
                output_tokens=safe_int(b["output"]),
                turn_count=safe_int(b["turns"]),
                session_count=len(b["sessions"]),
                last_active=str(b["last"]) or None,
            )
            for m, b in models.items()
        ]
        stats.sort(key=lambda x: (x.total_tokens, x.turn_count), reverse=True)
        sessions.sort(key=lambda s: (s.updated_at or "", s.total_tokens), reverse=True)
        return AgentReport(agent_name=self.name, models=stats, recent_sessions=sessions)
