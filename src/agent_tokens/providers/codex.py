"""Provider for OpenAI Codex CLI/Desktop rollout sessions."""

import glob
import json
import os
from typing import Dict, Optional

from agent_tokens.models import AgentReport, TokenStats, SessionInfo
from agent_tokens.providers._util import (
    file_is_today,
    is_today_str,
    parse_iso_to_local,
    safe_int,
)
from agent_tokens.providers.base import BaseProvider

_UNKNOWN_MODEL = "codex-unknown"


def _parse_rollout(path: str) -> Optional[Dict[str, object]]:
    """Extract cumulative token usage + metadata from one rollout JSONL file.

    Codex appends ``event_msg`` records with ``type == 'token_count'`` whose
    ``info.total_token_usage`` is cumulative for the session, so the last
    one wins. The model comes from ``turn_context`` payloads.
    """
    model = _UNKNOWN_MODEL
    timestamp: Optional[str] = None
    cwd: Optional[str] = None
    total: Optional[Dict[str, object]] = None
    turns = 0
    token_events = 0
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
                payload = rec.get("payload", {}) if isinstance(rec.get("payload"), dict) else {}
                if rtype == "session_meta" and isinstance(payload, dict):
                    timestamp = payload.get("timestamp") or timestamp
                    cwd = payload.get("cwd") or cwd
                elif rtype == "turn_context" and isinstance(payload, dict):
                    if isinstance(payload.get("model"), str) and payload["model"]:
                        model = payload["model"]
                    turns += 1
                elif rtype == "event_msg":
                    # Shape: {"type": "event_msg", "payload": {"type": "token_count", "info": {...}}}
                    if not isinstance(payload, dict):
                        continue
                    if payload.get("type") == "token_count":
                        info = payload.get("info", {}) if isinstance(payload, dict) else {}
                        tu = info.get("total_token_usage", {}) if isinstance(info, dict) else {}
                        if isinstance(tu, dict) and tu:
                            total = tu
                            token_events += 1
    except OSError:
        return None
    if total is None:
        return None
    return {
        "model": model,
        "timestamp": timestamp,
        "cwd": cwd,
        "total": total,
        # Older rollouts lack turn_context records; each token_count event
        # marks model activity, so it doubles as a turns fallback.
        "turns": turns or token_events,
    }


class CodexProvider(BaseProvider):
    """Parses ``~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl``."""

    def __init__(self, base_dir: Optional[str] = None):
        self.base_dir = base_dir or os.path.expanduser("~/.codex/sessions")

    @property
    def name(self) -> str:
        return "Codex"

    def is_available(self) -> bool:
        return os.path.isdir(self.base_dir)

    def get_report(self, today_only: bool = False) -> Optional[AgentReport]:
        if not self.is_available():
            return None

        models: Dict[str, Dict[str, int]] = {}
        model_last_active: Dict[str, str] = {}
        sessions = []

        for path in sorted(glob.glob(os.path.join(self.base_dir, "**", "rollout-*.jsonl"), recursive=True)):
            parsed = _parse_rollout(path)
            if not parsed:
                continue
            total = parsed["total"]
            ts = parsed.get("timestamp")
            local_ts = parse_iso_to_local(ts)
            if today_only and not (is_today_str(ts) or file_is_today(path)):
                continue

            in_tokens = safe_int(total.get("input_tokens"))
            cached_in = safe_int(total.get("cached_input_tokens"))
            cache_write = safe_int(total.get("cache_write_input_tokens"))
            out_tokens = safe_int(total.get("output_tokens"))
            reasoning = safe_int(total.get("reasoning_output_tokens"))
            # Codex reports cached input *within* input_tokens; store the
            # non-cached portion as input and cached as cache_read so the
            # dashboard columns stay meaningful and the total stays exact.
            net_input = max(in_tokens - cached_in, 0)
            if not (net_input or out_tokens or reasoning or cached_in or cache_write):
                # Older rollouts only record a lump total_tokens figure.
                net_input = safe_int(total.get("total_tokens"))
            model_id = str(parsed.get("model") or _UNKNOWN_MODEL)
            turns = safe_int(parsed.get("turns"))

            bucket = models.setdefault(
                model_id,
                {"input": 0, "output": 0, "reasoning": 0, "cached": 0,
                 "cache_write": 0, "turns": 0, "sessions": set()},
            )
            bucket["input"] += net_input
            bucket["output"] += out_tokens
            bucket["reasoning"] += reasoning
            bucket["cached"] += cached_in
            bucket["cache_write"] += cache_write
            bucket["turns"] += turns
            bucket["sessions"].add(path)
            if local_ts and local_ts > model_last_active.get(model_id, ""):
                model_last_active[model_id] = local_ts

            cwd = parsed.get("cwd") or ""
            title = os.path.basename(str(cwd).rstrip("/")) if cwd else os.path.basename(path)
            sessions.append(
                SessionInfo(
                    session_id=os.path.basename(path)[:36],
                    title=title or "codex-session",
                    model_id=model_id,
                    input_tokens=net_input,
                    output_tokens=out_tokens,
                    reasoning_tokens=reasoning,
                    cache_read_tokens=cached_in,
                    cache_write_tokens=cache_write,
                    turn_count=turns,
                    updated_at=local_ts or None,
                )
            )

        stats = [
            TokenStats(
                model_id=m,
                input_tokens=b["input"],
                output_tokens=b["output"],
                reasoning_tokens=b["reasoning"],
                cache_read_tokens=b["cached"],
                cache_write_tokens=b["cache_write"],
                turn_count=b["turns"],
                session_count=len(b["sessions"]),
                last_active=model_last_active.get(m),
            )
            for m, b in models.items()
        ]
        stats.sort(key=lambda x: x.total_tokens, reverse=True)
        sessions.sort(key=lambda s: (s.updated_at or "", s.total_tokens), reverse=True)
        return AgentReport(agent_name=self.name, models=stats, recent_sessions=sessions)
