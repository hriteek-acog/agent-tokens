"""Provider for extracting token usage from Claude Code CLI cache."""

import json
import os
from datetime import date
from typing import Dict, Optional

from agent_tokens.models import AgentReport, TokenStats
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


class ClaudeCodeProvider(BaseProvider):
    """Parses ~/.claude/stats-cache.json.

    All-time data comes from ``modelUsage`` (full input/output/cache
    breakdown). Daily data comes from ``dailyModelTokens`` which, in schema
    v5, only carries per-model totals — see ``_split_total_proportionally``.
    """

    def __init__(self, stats_path: Optional[str] = None):
        self.stats_path = stats_path or os.path.expanduser("~/.claude/stats-cache.json")

    @property
    def name(self) -> str:
        return "Claude Code"

    def is_available(self) -> bool:
        return os.path.exists(self.stats_path)

    def get_report(self, today_only: bool = False) -> Optional[AgentReport]:
        if not self.is_available():
            return None

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
            return AgentReport(agent_name=self.name, models=models)

        # --today: support both the legacy per-model breakdown schema and
        # the current v5 ``tokensByModel`` totals schema.
        today_str = date.today().isoformat()
        daily = data.get("dailyModelTokens", [])
        if not isinstance(daily, list):
            return AgentReport(agent_name=self.name)

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
        return AgentReport(agent_name=self.name, models=models)
