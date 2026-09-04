"""Shared transcript scanning for file-based agent providers.

Gemini CLI, Qwen Code, Pi, and DeepSeek all persist JSON/JSONL chat
transcripts whose schemas drift between releases. This module centralises
the defensive parsing (bounded recursion, size caps, today filtering) so
providers stay thin and no provider imports from another provider.
"""

import glob
import json
import os
from datetime import datetime
from typing import Any, Dict, FrozenSet, List, Optional

from agent_tokens.models import AgentReport, SessionInfo, TokenStats
from agent_tokens.providers._util import file_is_today, safe_int

_TOKEN_KEYS = {
    "inputtokens": "input",
    "outputtokens": "output",
    "cachedinputtokens": "cached",
    "cachereadinputtokens": "cached",
    "cachecreationinputtokens": "cache_write",
    "reasoningoutputtokens": "reasoning",
    "reasoningtokens": "reasoning",
}

_MAX_DEPTH = 6
_MAX_NODES = 5000
_MAX_FILE_BYTES = 10 * 1024 * 1024
_MAX_JSONL_LINES = 2000
_DEFAULT_SESSION_LIMIT = 25


def _normalise_key(key: object) -> str:
    return str(key).replace("_", "").replace("-", "").lower()


def _walk(node: Any, depth: int, acc: Dict[str, int], counter: List[int]) -> None:
    """Recursively sum recognised token fields and count user messages."""
    counter[0] += 1
    if counter[0] > _MAX_NODES or depth > _MAX_DEPTH:
        return
    if isinstance(node, dict):
        for key, value in node.items():
            bucket = _TOKEN_KEYS.get(_normalise_key(key))
            if bucket is not None and isinstance(value, (int, float)) and not isinstance(
                value, bool
            ):
                acc[bucket] += max(int(value), 0)
            elif key == "type" and value == "user" and isinstance(node.get("content"), str):
                acc["_user_msgs"] += 1
            elif key == "role" and value == "user":
                acc["_user_msgs"] += 1
            else:
                _walk(value, depth + 1, acc, counter)
    elif isinstance(node, list):
        for item in node:
            _walk(item, depth + 1, acc, counter)


def _load_doc(path: str) -> Any:
    """Load a JSON document; JSONL lines become a list (capped)."""
    if path.endswith(".jsonl"):
        docs = []
        with open(path, "r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    docs.append(json.loads(line))
                except ValueError:
                    continue
                if len(docs) >= _MAX_JSONL_LINES:
                    break
        return docs
    with open(path, "r", encoding="utf-8", errors="ignore") as handle:
        return json.load(handle)


def _file_mtime_label(path: str) -> Optional[str]:
    try:
        return datetime.fromtimestamp(os.stat(path).st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    except OSError:
        return None


def scan_transcript_dir(root: str, today_only: bool) -> List[Dict[str, Any]]:
    """Scan ``root`` for JSON/JSONL transcripts; one dict per file found."""
    found: List[Dict[str, Any]] = []
    if not os.path.isdir(root):
        return found
    paths = sorted(glob.glob(os.path.join(root, "**", "*.json"), recursive=True))
    paths += sorted(glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True))
    for path in paths:
        if today_only and not file_is_today(path):
            continue
        try:
            if os.path.getsize(path) > _MAX_FILE_BYTES:
                continue
            doc = _load_doc(path)
        except (OSError, ValueError):
            continue
        acc = {
            "input": 0,
            "output": 0,
            "cached": 0,
            "cache_write": 0,
            "reasoning": 0,
            "_user_msgs": 0,
        }
        _walk(doc, 0, acc, [0])
        found.append(
            {
                "path": path,
                "input": acc["input"],
                "output": acc["output"],
                "cached": acc["cached"],
                "cache_write": acc["cache_write"],
                "reasoning": acc["reasoning"],
                "turns": acc["_user_msgs"],
                "mtime": _file_mtime_label(path),
            }
        )
    return found


def dedupe_chats(
    chats: List[Dict[str, Any]],
    exclude_segments: FrozenSet[str] = frozenset(),
) -> List[Dict[str, Any]]:
    """Dedupe scans by path, dropping files under excluded dir segments."""
    unique: List[Dict[str, Any]] = []
    seen = set()
    for chat in chats:
        if exclude_segments and exclude_segments.intersection(chat["path"].split(os.sep)):
            continue
        if chat["path"] not in seen:
            seen.add(chat["path"])
            unique.append(chat)
    return unique


def _chat_session(
    chat: Dict[str, Any], model_id: str, default_title: str
) -> SessionInfo:
    raw_path = str(chat.get("path", ""))
    title = os.path.basename(raw_path)[:40] or default_title
    return SessionInfo(
        session_id=os.path.basename(raw_path)[:36] or "chat",
        title=title,
        model_id=model_id,
        input_tokens=safe_int(chat.get("input")),
        output_tokens=safe_int(chat.get("output")),
        reasoning_tokens=safe_int(chat.get("reasoning")),
        cache_read_tokens=safe_int(chat.get("cached")),
        cache_write_tokens=safe_int(chat.get("cache_write")),
        turn_count=safe_int(chat.get("turns")),
        updated_at=str(chat.get("mtime") or "") or None,
    )


def build_token_report(
    agent_name: str,
    model_id: str,
    chats: List[Dict[str, Any]],
    default_title: str = "chat",
    limit: int = _DEFAULT_SESSION_LIMIT,
) -> AgentReport:
    """Aggregate scanned transcript dicts into an AgentReport."""
    sessions = [
        _chat_session(c, model_id, default_title)
        for c in sorted(chats, key=lambda x: str(x.get("mtime") or ""), reverse=True)[
            :limit
        ]
    ]
    models = []
    if chats:
        last = max((str(c.get("mtime") or "") for c in chats), default="")
        models.append(
            TokenStats(
                model_id=model_id,
                input_tokens=sum(safe_int(c.get("input")) for c in chats),
                output_tokens=sum(safe_int(c.get("output")) for c in chats),
                reasoning_tokens=sum(safe_int(c.get("reasoning")) for c in chats),
                cache_read_tokens=sum(safe_int(c.get("cached")) for c in chats),
                cache_write_tokens=sum(safe_int(c.get("cache_write")) for c in chats),
                turn_count=sum(safe_int(c.get("turns")) for c in chats),
                session_count=len(chats),
                last_active=last or None,
            )
        )
    return AgentReport(agent_name=agent_name, models=models, recent_sessions=sessions)


def build_activity_report(
    agent_name: str,
    model_id: str,
    sessions: List[SessionInfo],
    limit: int = _DEFAULT_SESSION_LIMIT,
) -> AgentReport:
    """Build a report for agents without local token telemetry.

    Session/turn activity is real; the single model bucket carries
    session counts with zero tokens rather than invented figures.
    """
    ordered = sorted(sessions, key=lambda s: s.updated_at or "", reverse=True)
    models = []
    if ordered:
        models.append(
            TokenStats(
                model_id=model_id,
                turn_count=sum(s.turn_count or 0 for s in ordered),
                session_count=len(ordered),
                last_active=ordered[0].updated_at,
            )
        )
    return AgentReport(agent_name=agent_name, models=models, recent_sessions=ordered[:limit])
