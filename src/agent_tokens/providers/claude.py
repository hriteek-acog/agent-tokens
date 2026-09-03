"""Provider for extracting token usage from Claude Code CLI cache."""

import json
import os
from datetime import date
from typing import Optional

from agent_tokens.models import AgentReport, TokenStats
from agent_tokens.providers.base import BaseProvider


class ClaudeCodeProvider(BaseProvider):
    """Parses ~/.claude/stats-cache.json."""

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
        except (OSError, json.JSONDecodeError):
            return None

        models = []

        if today_only:
            today_str = date.today().isoformat()
            daily_models = data.get("dailyModelTokens", [])
            today_data = [d for d in daily_models if d.get("date") == today_str]
            aggregated = {}
            for entry in today_data:
                m = entry.get("model", "unknown")
                if m not in aggregated:
                    aggregated[m] = {
                        "input": 0,
                        "output": 0,
                        "cache_read": 0,
                        "cache_write": 0,
                    }
                aggregated[m]["input"] += entry.get("inputTokens", 0)
                aggregated[m]["output"] += entry.get("outputTokens", 0)
                aggregated[m]["cache_read"] += entry.get("cacheReadInputTokens", 0)
                aggregated[m]["cache_write"] += entry.get("cacheCreationInputTokens", 0)

            for m_id, stats in aggregated.items():
                models.append(
                    TokenStats(
                        model_id=m_id,
                        input_tokens=stats["input"],
                        output_tokens=stats["output"],
                        cache_read_tokens=stats["cache_read"],
                        cache_write_tokens=stats["cache_write"],
                    )
                )
        else:
            model_usage = data.get("modelUsage", {})
            for m_id, stats in model_usage.items():
                models.append(
                    TokenStats(
                        model_id=m_id,
                        input_tokens=stats.get("inputTokens", 0),
                        output_tokens=stats.get("outputTokens", 0),
                        cache_read_tokens=stats.get("cacheReadInputTokens", 0),
                        cache_write_tokens=stats.get("cacheCreationInputTokens", 0),
                    )
                )

        models.sort(key=lambda x: x.total_tokens, reverse=True)
        return AgentReport(agent_name=self.name, models=models)
