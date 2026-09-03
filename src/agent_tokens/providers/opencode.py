"""Provider for extracting token usage from OpenCode SQLite database."""

import os
import sqlite3
from datetime import datetime, date
from typing import List, Optional

from agent_tokens.models import AgentReport, TokenStats, SessionInfo
from agent_tokens.providers.base import BaseProvider

_RECENT_SESSION_LIMIT = 25


class OpenCodeProvider(BaseProvider):
    """Parses ~/.local/share/opencode/opencode.db.

    Reads the ``session`` table (tokens_input/output/reasoning/cache_read/
    cache_write + ``time_updated`` in epoch milliseconds). Opened read-only
    so a running OpenCode instance is never locked.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or os.path.expanduser("~/.local/share/opencode/opencode.db")

    @property
    def name(self) -> str:
        return "OpenCode"

    def is_available(self) -> bool:
        return os.path.exists(self.db_path)

    def _connect(self) -> sqlite3.Connection:
        # Read-only connection: never blocks writers, fails fast if missing.
        uri = f"file:{self.db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5.0)
        conn.row_factory = sqlite3.Row
        return conn

    def get_report(self, today_only: bool = False) -> Optional[AgentReport]:
        if not self.is_available():
            return None

        midnight_ms: Optional[int] = None
        if today_only:
            midnight = datetime.combine(date.today(), datetime.min.time())
            midnight_ms = int(midnight.timestamp() * 1000)

        try:
            with self._connect() as conn:
                cur = conn.cursor()
                # Bail out gracefully on fresh/older DBs without the table.
                cur.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='session'"
                )
                if not cur.fetchone():
                    return AgentReport(agent_name=self.name)

                params: List[object] = []
                where = ""
                if midnight_ms is not None:
                    where = "WHERE time_updated >= ?"
                    params.append(midnight_ms)

                cur.execute(
                    f"""
                    SELECT
                        json_extract(model, '$.id') as model_id,
                        count(id) as session_count,
                        coalesce(sum(tokens_input), 0) as in_tokens,
                        coalesce(sum(tokens_output), 0) as out_tokens,
                        coalesce(sum(tokens_reasoning), 0) as reasoning_tokens,
                        coalesce(sum(tokens_cache_read), 0) as cache_read,
                        coalesce(sum(tokens_cache_write), 0) as cache_write,
                        max(datetime(time_updated/1000, 'unixepoch', 'localtime')) as last_active
                    FROM session
                    {where}
                    GROUP BY model_id
                    ORDER BY
                        (coalesce(sum(tokens_input),0)
                         + coalesce(sum(tokens_output),0)
                         + coalesce(sum(tokens_reasoning),0)
                         + coalesce(sum(tokens_cache_read),0)
                         + coalesce(sum(tokens_cache_write),0)) DESC
                    """,
                    params,
                )
                models = [
                    TokenStats(
                        model_id=r["model_id"] or "unknown",
                        input_tokens=r["in_tokens"] or 0,
                        output_tokens=r["out_tokens"] or 0,
                        reasoning_tokens=r["reasoning_tokens"] or 0,
                        cache_read_tokens=r["cache_read"] or 0,
                        cache_write_tokens=r["cache_write"] or 0,
                        session_count=r["session_count"] or 0,
                        last_active=r["last_active"],
                    )
                    for r in cur.fetchall()
                ]

                # Recent sessions are useful for both scopes; for all-time we
                # show the most recently active ones.
                cur.execute(
                    f"""
                    SELECT id, title, json_extract(model, '$.id'),
                           tokens_input, tokens_output,
                           tokens_reasoning, tokens_cache_read, tokens_cache_write,
                           datetime(time_updated/1000, 'unixepoch', 'localtime')
                    FROM session
                    {where}
                    ORDER BY time_updated DESC
                    LIMIT ?
                    """,
                    [*params, _RECENT_SESSION_LIMIT],
                )
                sessions = [
                    SessionInfo(
                        session_id=r[0] or "unknown",
                        title=r[1] or (r[0][:18] if r[0] else "untitled"),
                        model_id=r[2] or "unknown",
                        input_tokens=r[3] or 0,
                        output_tokens=r[4] or 0,
                        reasoning_tokens=r[5] or 0,
                        cache_read_tokens=r[6] or 0,
                        cache_write_tokens=r[7] or 0,
                        updated_at=r[8],
                    )
                    for r in cur.fetchall()
                ]
        except sqlite3.Error:
            return AgentReport(agent_name=self.name)

        return AgentReport(agent_name=self.name, models=models, recent_sessions=sessions)
