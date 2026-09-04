"""Provider for Google Gemini CLI chat transcripts.

Gemini CLI (``google-gemini/gemini-cli``) persists per-project chat files
under ``~/.gemini/tmp/<project-hash>/``. Transcript schemas drift between
releases, so parsing is defensive: each ``*.json`` chat file counts as one
session, user messages count as turns, and any recognised token fields
found anywhere in the document are summed (bounded recursion).
"""

import glob
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from agent_tokens.models import AgentReport, TokenStats, SessionInfo
from agent_tokens.providers._util import file_is_today, safe_int
from agent_tokens.providers.base import BaseProvider

_MODEL_ID = "gemini-cli"

_TOKEN_KEYS = {
    "input_tokens": ("input",),
    "inputtokens": ("input",),
    "output_tokens": ("output",),
    "outputtokens": ("output",),
    "cached_input_tokens": ("cached",),
    "cachereadinputtokens": ("cached",),
    "reasoning_output_tokens": ("reasoning",),
    "reasoningtokens": ("reasoning",),
}

_MAX_DEPTH = 6
_MAX_NODES = 5000


def _walk(node: Any, depth: int, acc: Dict[str, int], counter: List[int]) -> None:
    """Recursively sum recognised token fields and count user messages."""
    counter[0] += 1
    if counter[0] > _MAX_NODES or depth > _MAX_DEPTH:
        return
    if isinstance(node, dict):
        for k, v in node.items():
            kl = str(k).replace("_", "").replace("-", "").lower()
            if kl in _TOKEN_KEYS and isinstance(v, (int, float)) and not isinstance(v, bool):
                acc[_TOKEN_KEYS[kl][0]] += max(int(v), 0)
            elif k == "type" and v == "user" and isinstance(node.get("content"), str):
                acc["_user_msgs"] += 1
            elif k == "role" and v == "user":
                acc["_user_msgs"] += 1
            else:
                _walk(v, depth + 1, acc, counter)
    elif isinstance(node, list):
        for item in node:
            _walk(item, depth + 1, acc, counter)


def _load_doc(path: str):
    """Load a JSON or JSONL document; JSONL lines become a list."""
    if path.endswith(".jsonl"):
        docs = []
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    docs.append(json.loads(line))
                except ValueError:
                    continue
                if len(docs) > 2000:
                    break
        return docs
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return json.load(f)


def scan_chat_dir(tmp_dir: str, today_only: bool) -> List[Dict[str, Any]]:
    """Scan a Gemini-fork tmp dir; one dict per chat file found."""
    out: List[Dict[str, Any]] = []
    if not os.path.isdir(tmp_dir):
        return out
    paths = sorted(glob.glob(os.path.join(tmp_dir, "**", "*.json"), recursive=True))
    paths += sorted(glob.glob(os.path.join(tmp_dir, "**", "*.jsonl"), recursive=True))
    for path in paths:
        if today_only and not file_is_today(path):
            continue
        try:
            if os.path.getsize(path) > 10 * 1024 * 1024:
                continue
            doc = _load_doc(path)
        except (OSError, ValueError):
            continue
        acc = {"input": 0, "output": 0, "cached": 0, "reasoning": 0, "_user_msgs": 0}
        _walk(doc, 0, acc, [0])
        try:
            mtime = datetime.fromtimestamp(os.stat(path).st_mtime).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        except OSError:
            mtime = None
        out.append(
            {
                "path": path,
                "input": acc["input"],
                "output": acc["output"],
                "cached": acc["cached"],
                "reasoning": acc["reasoning"],
                "turns": acc["_user_msgs"],
                "mtime": mtime,
            }
        )
    return out


class GeminiCliProvider(BaseProvider):
    """Reads ``~/.gemini/tmp`` Gemini CLI chat transcripts."""

    def __init__(self, tmp_dir: Optional[str] = None):
        self.tmp_dir = tmp_dir or os.path.expanduser("~/.gemini/tmp")

    @property
    def name(self) -> str:
        return "Gemini CLI"

    def is_available(self) -> bool:
        return os.path.isdir(self.tmp_dir)

    def get_report(self, today_only: bool = False) -> Optional[AgentReport]:
        if not self.is_available():
            return None
        chats = scan_chat_dir(self.tmp_dir, today_only)
        return build_report(self.name, _MODEL_ID, chats)


def build_report(
    agent_name: str, model_id: str, chats: List[Dict[str, Any]]
) -> AgentReport:
    """Aggregate scanned chat dicts into an AgentReport (shared with Qwen)."""
    total_in = sum(safe_int(c.get("input")) for c in chats)
    total_out = sum(safe_int(c.get("output")) for c in chats)
    total_cached = sum(safe_int(c.get("cached")) for c in chats)
    total_reason = sum(safe_int(c.get("reasoning")) for c in chats)
    total_turns = sum(safe_int(c.get("turns")) for c in chats)
    last = max((str(c.get("mtime") or "") for c in chats), default="")

    sessions = []
    for c in sorted(chats, key=lambda x: str(x.get("mtime") or ""), reverse=True)[:25]:
        title = os.path.basename(str(c.get("path", "")))[:40] or "gemini-chat"
        sessions.append(
            SessionInfo(
                session_id=os.path.basename(str(c.get("path", "")))[:36] or "chat",
                title=title,
                model_id=model_id,
                input_tokens=safe_int(c.get("input")),
                output_tokens=safe_int(c.get("output")),
                reasoning_tokens=safe_int(c.get("reasoning")),
                cache_read_tokens=safe_int(c.get("cached")),
                turn_count=safe_int(c.get("turns")),
                updated_at=str(c.get("mtime") or "") or None,
            )
        )

    models = []
    if chats:
        models.append(
            TokenStats(
                model_id=model_id,
                input_tokens=total_in,
                output_tokens=total_out,
                reasoning_tokens=total_reason,
                cache_read_tokens=total_cached,
                turn_count=total_turns,
                session_count=len(chats),
                last_active=last or None,
            )
        )
    return AgentReport(agent_name=agent_name, models=models, recent_sessions=sessions)
