"""Shared helpers for agent providers."""

import os
import sqlite3
from datetime import date, datetime
from typing import Any, Optional


def safe_int(value: Any, default: int = 0) -> int:
    """Coerce DB/JSON numbers (or numeric strings) to non-negative int."""
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return max(value, 0)
    if isinstance(value, float):
        return max(int(value), 0)
    if isinstance(value, str):
        try:
            return max(int(float(value.strip())), 0)
        except (ValueError, AttributeError):
            return default
    return default


def connect_ro(path: str, timeout: float = 5.0) -> sqlite3.Connection:
    """Open a SQLite DB read-only so running agents are never locked."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=timeout)
    conn.row_factory = sqlite3.Row
    return conn


def is_today_str(ts: Any) -> bool:
    """True if an ISO-ish timestamp falls on local today (UTC tolerated)."""
    if not isinstance(ts, str) or len(ts) < 10:
        return False
    today = date.today().isoformat()
    if ts[:10] == today:
        return True
    try:
        from datetime import timezone

        if ts[:10] == datetime.now(timezone.utc).date().isoformat():
            return True
    except Exception:
        pass
    return False


def file_is_today(path: str) -> bool:
    try:
        return datetime.fromtimestamp(os.stat(path).st_mtime).date() == date.today()
    except OSError:
        return False


def parse_iso_to_local(ts: Any) -> Optional[str]:
    """Normalise ISO timestamps to 'YYYY-MM-DD HH:MM:SS' for display."""
    if not isinstance(ts, str) or not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, OverflowError):
        return ts[:19] if len(ts) >= 19 else ts
