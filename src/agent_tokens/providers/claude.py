"""Provider for extracting token usage from Claude Code."""

import glob
import json
import os
from datetime import date, datetime
from typing import Dict, List, Optional

from agent_tokens.models import AgentReport, SessionInfo, TokenStats
from agent_tokens.providers._util import parse_iso_to_local, safe_int
from agent_tokens.providers.base import BaseProvider


def _safe_int(value: object, default: int = 0) -> int:
    """Coerce JSON numbers (or numeric strings) to int, falling back safely."""
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value))
        except ValueError:
            return default
    return default


def _split_total_proportionally(
    model_id: str, total: int, model_usage: Dict[str, dict]
) -> TokenStats:
    """Split a day-total into input/output/cache buckets.

    ``dailyModelTokens`` (schema v5) only records ``tokensByModel`` totals,
    so for ``--today`` we apportion the total using the model's all-time
    ratios from ``modelUsage``. Totals stay exact; the breakdown is marked
    as an estimate in spirit. Falls back to ``input_tokens`` when no
    all-time baseline exists for the model.
    """
    baseline = model_usage.get(model_id)
    if not isinstance(baseline, dict):
        return TokenStats(model_id=model_id, input_tokens=total)

    parts = {
        "input": _safe_int(baseline.get("inputTokens")),
        "output": _safe_int(baseline.get("outputTokens")),
        "cache_read": _safe_int(baseline.get("cacheReadInputTokens")),
        "cache_write": _safe_int(baseline.get("cacheCreationInputTokens")),
    }
    base_total = sum(parts.values())
    if base_total <= 0 or total <= 0:
        return TokenStats(model_id=model_id, input_tokens=total)

    allocated = {k: (v * total) // base_total for k, v in parts.items()}
    # Fix rounding remainder so the buckets sum exactly to ``total``.
    remainder = total - sum(allocated.values())
    if remainder:
        # Credit the largest bucket to minimise relative error.
        biggest = max(parts, key=lambda k: parts[k])
        allocated[biggest] += remainder

    return TokenStats(
        model_id=model_id,
        input_tokens=allocated["input"],
        output_tokens=allocated["output"],
        cache_read_tokens=allocated["cache_read"],
        cache_write_tokens=allocated["cache_write"],
    )


def _local_date(ts: object) -> Optional[str]:
    if not isinstance(ts, str) or not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().date().isoformat()
    except ValueError:
        return None


def _read_transcript_usage(projects_dir: str, after: Optional[str]) -> List[dict]:
    """One record per API message in ``projects/**/*.jsonl`` dated after ``after``.

    Claude Code writes a line per content block, each repeating the
    message's ``usage``; dedupe by message id so nothing counts twice.
    Files not modified after ``after`` are skipped unread.
    """
    seen: Dict[str, dict] = {}
    for path in glob.glob(os.path.join(projects_dir, "**", "*.jsonl"), recursive=True):
        try:
            mtime = datetime.fromtimestamp(os.stat(path).st_mtime).date().isoformat()
        except OSError:
            continue
        if after and mtime <= after:
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if '"usage"' not in line:
                        continue
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    msg = rec.get("message") if isinstance(rec, dict) else None
                    if not isinstance(msg, dict) or not isinstance(msg.get("usage"), dict):
                        continue
                    day = _local_date(rec.get("timestamp"))
                    if not day or (after and day <= after):
                        continue
                    model = msg.get("model")
                    if not isinstance(model, str) or not model or model.startswith("<"):
                        continue  # e.g. "<synthetic>" placeholder messages
                    u = msg["usage"]
                    key = str(msg.get("id") or rec.get("requestId") or rec.get("uuid"))
                    seen[key] = {
                        "model": model,
                        "session": str(rec.get("sessionId") or os.path.basename(path)),
                        "cwd": rec.get("cwd") or "",
                        "timestamp": rec.get("timestamp"),
                        "input": safe_int(u.get("input_tokens")),
                        "output": safe_int(u.get("output_tokens")),
                        "cache_read": safe_int(u.get("cache_read_input_tokens")),
                        "cache_write": safe_int(u.get("cache_creation_input_tokens")),
                    }
        except OSError:
            continue
    return list(seen.values())


def _aggregate(records: List[dict]):
    models: Dict[str, TokenStats] = {}
    model_sessions: Dict[str, set] = {}
    # One session row per model, so a mid-session /model switch shows both.
    sessions: Dict[tuple, SessionInfo] = {}
    for r in records:
        local_ts = parse_iso_to_local(r["timestamp"])
        m = models.setdefault(r["model"], TokenStats(model_id=r["model"]))
        s = sessions.setdefault(
            (r["session"], r["model"]),
            SessionInfo(
                session_id=r["session"],
                title=os.path.basename(str(r["cwd"]).rstrip("/")),
                model_id=r["model"],
            ),
        )
        for obj in (m, s):
            obj.input_tokens += r["input"]
            obj.output_tokens += r["output"]
            obj.cache_read_tokens += r["cache_read"]
            obj.cache_write_tokens += r["cache_write"]
            obj.turn_count += 1
        model_sessions.setdefault(r["model"], set()).add(r["session"])
        if local_ts and local_ts > (m.last_active or ""):
            m.last_active = local_ts
        if local_ts and local_ts > (s.updated_at or ""):
            s.updated_at = local_ts
    for model_id, ids in model_sessions.items():
        models[model_id].session_count = len(ids)
    return models, list(sessions.values())


class ClaudeCodeProvider(BaseProvider):
    """Parses ~/.claude/stats-cache.json plus ~/.claude/projects transcripts.

    Claude Code only refreshes the stats cache when ``/stats`` runs, so it
    is authoritative up to its ``lastComputedDate`` and transcripts cover
    every day after. Transcripts alone aren't enough: Claude Code prunes
    them after ``cleanupPeriodDays``.
    """

    def __init__(self, stats_path: Optional[str] = None, projects_dir: Optional[str] = None):
        self.stats_path = stats_path or os.path.expanduser("~/.claude/stats-cache.json")
        self.projects_dir = projects_dir or os.path.join(
            os.path.dirname(self.stats_path), "projects"
        )

    @property
    def name(self) -> str:
        return "Claude Code"

    def is_available(self) -> bool:
        return os.path.exists(self.stats_path) or os.path.isdir(self.projects_dir)

    def get_report(self, today_only: bool = False) -> Optional[AgentReport]:
        if not self.is_available():
            return None
        cache = self._get_cache_report(today_only)
        last_computed = cache[1] if cache else None
        today_str = date.today().isoformat()
        if today_only:
            if last_computed and last_computed >= today_str:
                return cache[0]
            after = (date.fromordinal(date.today().toordinal() - 1)).isoformat()
        else:
            after = last_computed

        models, sessions = _aggregate(_read_transcript_usage(self.projects_dir, after))
        if cache:
            for m in cache[0].models:
                live = models.get(m.model_id)
                if live is None:
                    models[m.model_id] = m
                    continue
                live.input_tokens += m.input_tokens
                live.output_tokens += m.output_tokens
                live.cache_read_tokens += m.cache_read_tokens
                live.cache_write_tokens += m.cache_write_tokens
        stats = sorted(models.values(), key=lambda x: x.total_tokens, reverse=True)
        sessions.sort(key=lambda s: (s.updated_at or "", s.total_tokens), reverse=True)
        return AgentReport(agent_name=self.name, models=stats, recent_sessions=sessions)

    def _get_cache_report(self, today_only: bool):
        """``(report, lastComputedDate)`` from the stats cache, or None."""
        try:
            with open(self.stats_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            # OSError: unreadable file; ValueError: malformed JSON.
            return None

        if not isinstance(data, dict):
            return None

        model_usage = data.get("modelUsage", {})
        if not isinstance(model_usage, dict):
            model_usage = {}
        last_computed = data.get("lastComputedDate")

        if not today_only:
            models = []
            for m_id, stats in model_usage.items():
                if not isinstance(stats, dict):
                    continue
                models.append(
                    TokenStats(
                        model_id=str(m_id),
                        input_tokens=_safe_int(stats.get("inputTokens")),
                        output_tokens=_safe_int(stats.get("outputTokens")),
                        cache_read_tokens=_safe_int(stats.get("cacheReadInputTokens")),
                        cache_write_tokens=_safe_int(
                            stats.get("cacheCreationInputTokens")
                        ),
                        last_active=last_computed,
                    )
                )
            models.sort(key=lambda x: x.total_tokens, reverse=True)
            return AgentReport(agent_name=self.name, models=models), last_computed

        # --today: support both the legacy per-model breakdown schema and
        # the current v5 ``tokensByModel`` totals schema.
        today_str = date.today().isoformat()
        daily = data.get("dailyModelTokens", [])
        if not isinstance(daily, list):
            return AgentReport(agent_name=self.name), last_computed

        models = []
        for entry in daily:
            if not isinstance(entry, dict) or entry.get("date") != today_str:
                continue
            # Legacy schema: {"date", "model", "inputTokens", ...}
            if "model" in entry:
                models.append(
                    TokenStats(
                        model_id=str(entry.get("model", "unknown")),
                        input_tokens=_safe_int(entry.get("inputTokens")),
                        output_tokens=_safe_int(entry.get("outputTokens")),
                        cache_read_tokens=_safe_int(entry.get("cacheReadInputTokens")),
                        cache_write_tokens=_safe_int(
                            entry.get("cacheCreationInputTokens")
                        ),
                        last_active=today_str,
                    )
                )
                continue
            # Current schema: {"date", "tokensByModel": {model: total}}
            tokens_by_model = entry.get("tokensByModel", {})
            if not isinstance(tokens_by_model, dict):
                continue
            for m_id, total in tokens_by_model.items():
                total_int = _safe_int(total)
                if total_int <= 0:
                    continue
                stats = _split_total_proportionally(str(m_id), total_int, model_usage)
                stats.last_active = today_str
                models.append(stats)

        models.sort(key=lambda x: x.total_tokens, reverse=True)
        return AgentReport(agent_name=self.name, models=models), last_computed
