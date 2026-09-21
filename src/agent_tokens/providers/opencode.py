"""Provider for extracting token usage from OpenCode SQLite database."""

import os
import sqlite3
from datetime import datetime, date
from typing import Dict, List, Optional

from agent_tokens.models import AgentReport, TokenStats, SessionInfo
from agent_tokens.providers.base import BaseProvider

_RECENT_SESSION_LIMIT = 25


class OpenCodeProvider(BaseProvider):
    """Parses ~/.local/share/opencode/opencode.db.

    Reads assistant rows of the ``message`` table (per-message ``modelID``
    and tokens), falling back to the ``session`` table's totals on DBs
    without it. ``--today`` keeps sessions updated since local midnight.
    Opened read-only so a running OpenCode instance is never locked.
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

                cur.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='message'"
                )
                has_messages = cur.fetchone() is not None
                params: List[object] = []
                where = ""
                if midnight_ms is not None:
                    where = "AND s.time_updated >= ?"
                    params.append(midnight_ms)

                if has_messages:
                    # Per-message model: a session that switches models
                    # yields one row per model instead of crediting all
                    # tokens to the session's last model.
                    cur.execute(
                        f"""
                        SELECT s.id, s.title, json_extract(m.data, '$.modelID'),
                               sum(json_extract(m.data, '$.tokens.input')),
                               sum(json_extract(m.data, '$.tokens.output')),
                               sum(json_extract(m.data, '$.tokens.reasoning')),
                               sum(json_extract(m.data, '$.tokens.cache.read')),
                               sum(json_extract(m.data, '$.tokens.cache.write')),
                               datetime(max(m.time_updated)/1000, 'unixepoch', 'localtime'),
                               count(m.id)
                        FROM message m JOIN session s ON s.id = m.session_id
                        WHERE json_extract(m.data, '$.role') = 'assistant' {where}
                        GROUP BY s.id, json_extract(m.data, '$.modelID')
                        """,
                        params,
                    )
                else:
                    cur.execute(
                        f"""
                        SELECT s.id, s.title, json_extract(s.model, '$.id'),
                               s.tokens_input, s.tokens_output, s.tokens_reasoning,
                               s.tokens_cache_read, s.tokens_cache_write,
                               datetime(s.time_updated/1000, 'unixepoch', 'localtime'),
                               0
                        FROM session s
                        WHERE 1 {where}
                        """,
                        params,
                    )
                rows = [
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
                        turn_count=r[9] or 0,
                    )
                    for r in cur.fetchall()
                ]
        except sqlite3.Error:
            return AgentReport(agent_name=self.name)

        models: Dict[str, TokenStats] = {}
        model_sessions: Dict[str, set] = {}
        for r in rows:
            m = models.setdefault(r.model_id, TokenStats(model_id=r.model_id))
            m.input_tokens += r.input_tokens
            m.output_tokens += r.output_tokens
            m.reasoning_tokens += r.reasoning_tokens
            m.cache_read_tokens += r.cache_read_tokens
            m.cache_write_tokens += r.cache_write_tokens
            m.turn_count += r.turn_count
            model_sessions.setdefault(r.model_id, set()).add(r.session_id)
            if r.updated_at and r.updated_at > (m.last_active or ""):
                m.last_active = r.updated_at
        for model_id, ids in model_sessions.items():
            models[model_id].session_count = len(ids)

        stats = sorted(models.values(), key=lambda x: x.total_tokens, reverse=True)
        rows = [r for r in rows if r.total_tokens > 0]
        rows.sort(key=lambda r: r.updated_at or "", reverse=True)
        return AgentReport(
            agent_name=self.name, models=stats, recent_sessions=rows[:_RECENT_SESSION_LIMIT]
        )
