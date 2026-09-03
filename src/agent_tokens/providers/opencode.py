"""Provider for extracting token usage from OpenCode SQLite database."""

import os
import sqlite3
from datetime import datetime, date
from typing import Optional

from agent_tokens.models import AgentReport, TokenStats, SessionInfo
from agent_tokens.providers.base import BaseProvider


class OpenCodeProvider(BaseProvider):
    """Parses ~/.local/share/opencode/opencode.db."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or os.path.expanduser("~/.local/share/opencode/opencode.db")

    @property
    def name(self) -> str:
        return "OpenCode"

    def is_available(self) -> bool:
        return os.path.exists(self.db_path)

    def get_report(self, today_only: bool = False) -> Optional[AgentReport]:
        if not self.is_available():
            return None

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        time_filter = ""
        if today_only:
            midnight = datetime.combine(date.today(), datetime.min.time())
            midnight_ms = int(midnight.timestamp() * 1000)
            time_filter = f"WHERE time_updated >= {midnight_ms}"

        query = f"""
            SELECT 
                json_extract(model, '$.id') as model_id,
                count(id) as session_count,
                sum(tokens_input) as in_tokens,
                sum(tokens_output) as out_tokens,
                sum(tokens_reasoning) as reasoning_tokens,
                sum(tokens_cache_read) as cache_tokens,
                max(datetime(time_updated/1000, 'unixepoch', 'localtime')) as last_active
            FROM session
            {time_filter}
            GROUP BY model_id
            ORDER BY (sum(tokens_input) + sum(tokens_output) + sum(tokens_cache_read)) DESC
        """
        cur.execute(query)
        rows = cur.fetchall()

        models = []
        for r in rows:
            m_id, s_cnt, tin, tout, treas, tcache, last_act = r
            models.append(
                TokenStats(
                    model_id=m_id or "unknown",
                    input_tokens=tin or 0,
                    output_tokens=tout or 0,
                    reasoning_tokens=treas or 0,
                    cache_read_tokens=tcache or 0,
                    session_count=s_cnt or 0,
                    last_active=last_act,
                )
            )

        sessions = []
        if today_only:
            session_query = f"""
                SELECT id, title, json_extract(model, '$.id'), tokens_input, tokens_output,
                       tokens_reasoning, tokens_cache_read,
                       datetime(time_updated/1000, 'unixepoch', 'localtime')
                FROM session
                {time_filter}
                ORDER BY time_updated DESC
            """
            cur.execute(session_query)
            for s in cur.fetchall():
                sid, stitle, smodel, stin, stout, streas, stcache, stime = s
                sessions.append(
                    SessionInfo(
                        session_id=sid,
                        title=stitle,
                        model_id=smodel or "unknown",
                        input_tokens=stin or 0,
                        output_tokens=stout or 0,
                        reasoning_tokens=streas or 0,
                        cache_read_tokens=stcache or 0,
                        updated_at=stime,
                    )
                )

        conn.close()
        return AgentReport(agent_name=self.name, models=models, recent_sessions=sessions)
