"""Provider for Cline (VSCode extension) task histories.

Cline stores per-task directories under the extension's global storage
(``.../globalStorage/saoudrizwan.claude-dev/tasks/<taskId>/`` or the newer
``cline.cline`` id), each with ``api_conversation_history.json`` message
lists that may carry ``tokensIn``/``tokensOut``/``cacheReads``/
``cacheWrites`` counters. Everything is optional — tasks without usage
fields still count as activity with zero tokens.
"""

import glob
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from agent_tokens.models import AgentReport, TokenStats, SessionInfo
from agent_tokens.providers._util import safe_int
from agent_tokens.providers.base import BaseProvider

_DEFAULT_MODEL = "cline"

_STORAGE_IDS = ("saoudrizwan.claude-dev", "cline.cline")

_HISTORY_NAMES = ("api_conversation_history.json", "conversation_history.json")


def _candidate_roots() -> List[str]:
    roots = []
    home = os.path.expanduser("~")
    prefixes = [
        os.path.join(home, "Library/Application Support/Code/User/globalStorage"),
        os.path.join(home, ".config/Code/User/globalStorage"),
        os.path.join(home, ".vscode-server/data/Machine"),  # remote fallback
    ]
    for pre in prefixes:
        for sid in _STORAGE_IDS:
            tasks = os.path.join(pre, sid, "tasks")
            if os.path.isdir(tasks):
                roots.append(tasks)
    dot_cline = os.path.join(home, ".cline", "tasks")
    if os.path.isdir(dot_cline):
        roots.append(dot_cline)
    return roots


def _sum_history(path: str) -> Dict[str, Any]:
    """Sum usage counters from one conversation-history JSON file."""
    totals = {"in": 0, "out": 0, "cache_read": 0, "cache_write": 0, "turns": 0}
    try:
        if os.path.getsize(path) > 20 * 1024 * 1024:
            return totals
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return totals
    msgs = doc if isinstance(doc, list) else doc.get("messages", doc.get("history", []))
    if not isinstance(msgs, list):
        return totals
    for m in msgs:
        if not isinstance(m, dict):
            continue
        totals["in"] += safe_int(m.get("tokensIn", m.get("tokens_in", m.get("inputTokens"))))
        totals["out"] += safe_int(m.get("tokensOut", m.get("tokens_out", m.get("outputTokens"))))
        totals["cache_read"] += safe_int(m.get("cacheReads", m.get("cache_read_input_tokens")))
        totals["cache_write"] += safe_int(m.get("cacheWrites", m.get("cache_creation_input_tokens")))
        role = str(m.get("role", m.get("say", m.get("type", "")))).lower()
        if role in ("user", "human", "ask"):
            totals["turns"] += 1
    return totals


def _task_model(task_dir: str) -> str:
    for name in ("task_metadata.json", "metadata.json", "task.json"):
        p = os.path.join(task_dir, name)
        try:
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                meta = json.load(f)
            if isinstance(meta, dict):
                for k in ("model", "apiModelId", "modelId", "api_model_id"):
                    if meta.get(k):
                        return str(meta[k])
        except (OSError, ValueError):
            continue
    return _DEFAULT_MODEL


def _task_title(task_dir: str, fallback: str) -> str:
    for name in ("task_metadata.json", "metadata.json"):
        p = os.path.join(task_dir, name)
        try:
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                meta = json.load(f)
            if isinstance(meta, dict):
                for k in ("taskName", "task_title", "title", "task"):
                    if meta.get(k):
                        return str(meta[k])[:60]
        except (OSError, ValueError):
            continue
    return fallback


class ClineProvider(BaseProvider):
    """Reads Cline task histories from VSCode global storage."""

    def __init__(self, task_roots: Optional[List[str]] = None):
        self._roots = task_roots

    @property
    def name(self) -> str:
        return "Cline"

    def roots(self) -> List[str]:
        if self._roots is not None:
            return [r for r in self._roots if os.path.isdir(r)]
        return _candidate_roots()

    def is_available(self) -> bool:
        return bool(self.roots())

    def get_report(self, today_only: bool = False) -> Optional[AgentReport]:
        roots = self.roots()
        if not roots:
            return None

        models: Dict[str, Dict[str, Any]] = {}
        sessions: List[SessionInfo] = []
        today = datetime.now().date()

        for root in roots:
            try:
                task_dirs = sorted(
                    d for d in glob.glob(os.path.join(root, "*")) if os.path.isdir(d)
                )
            except OSError:
                continue
            for tdir in task_dirs:
                try:
                    mtime = datetime.fromtimestamp(os.stat(tdir).st_mtime)
                except OSError:
                    continue
                if today_only and mtime.date() != today:
                    continue
                stamp = mtime.strftime("%Y-%m-%d %H:%M:%S")
                agg = {"in": 0, "out": 0, "cache_read": 0, "cache_write": 0, "turns": 0}
                for hname in _HISTORY_NAMES:
                    hpath = os.path.join(tdir, hname)
                    if os.path.exists(hpath):
                        part = _sum_history(hpath)
                        for k in agg:
                            agg[k] += part[k]
                mid = _task_model(tdir)
                tid = os.path.basename(tdir)
                b = models.setdefault(
                    mid, {"in": 0, "out": 0, "cr": 0, "cw": 0, "turns": 0,
                          "sessions": set(), "last": ""}
                )
                b["in"] += agg["in"]
                b["out"] += agg["out"]
                b["cr"] += agg["cache_read"]
                b["cw"] += agg["cache_write"]
                b["turns"] += agg["turns"]
                b["sessions"].add(tid)
                b["last"] = max(str(b["last"]), stamp)
                sessions.append(
                    SessionInfo(
                        session_id=tid[:36],
                        title=_task_title(tdir, tid[:18]),
                        model_id=mid,
                        input_tokens=agg["in"],
                        output_tokens=agg["out"],
                        cache_read_tokens=agg["cache_read"],
                        cache_write_tokens=agg["cache_write"],
                        turn_count=agg["turns"],
                        updated_at=stamp,
                    )
                )

        stats = [
            TokenStats(
                model_id=m,
                input_tokens=safe_int(b["in"]),
                output_tokens=safe_int(b["out"]),
                cache_read_tokens=safe_int(b["cr"]),
                cache_write_tokens=safe_int(b["cw"]),
                turn_count=safe_int(b["turns"]),
                session_count=len(b["sessions"]),
                last_active=str(b["last"]) or None,
            )
            for m, b in models.items()
        ]
        stats.sort(key=lambda x: (x.total_tokens, x.turn_count), reverse=True)
        sessions.sort(key=lambda s: (s.updated_at or "", s.total_tokens), reverse=True)
        return AgentReport(agent_name=self.name, models=stats, recent_sessions=sessions)
