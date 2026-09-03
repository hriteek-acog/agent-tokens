"""Provider for extracting token usage from Google Antigravity (AGY) sessions."""

import glob
import os
import sqlite3
from collections import Counter
from datetime import datetime, date
from typing import Optional, Dict, Any, List

from agent_tokens.models import AgentReport, TokenStats, SessionInfo
from agent_tokens.providers.base import BaseProvider

_UNKNOWN_MODEL = "gemini-unknown"


def _parse_proto(buf: bytes) -> List[tuple]:
    """Lightweight pure-Python protobuf field decoder.

    Unknown 64-bit (wire type 1) and 32-bit (wire type 5) fields are
    skipped; malformed tails terminate parsing instead of raising.
    """
    pos = 0
    fields = []

    def read_varint(p: int):
        res = 0
        shift = 0
        while p < len(buf):
            b = buf[p]
            p += 1
            res |= (b & 0x7F) << shift
            if not (b & 0x80):
                break
            shift += 7
            if shift >= 64:  # corrupt varint guard
                return None, p
        return res, p

    size = len(buf)
    while pos < size:
        try:
            tag, pos = read_varint(pos)
            if tag is None:
                break
            field_num = tag >> 3
            wire_type = tag & 0x7
            if wire_type == 0:  # varint
                val, pos = read_varint(pos)
                if val is None:
                    break
                fields.append((field_num, "varint", val))
            elif wire_type == 1:  # 64-bit
                if pos + 8 > size:
                    break
                fields.append((field_num, "fixed64", buf[pos : pos + 8]))
                pos += 8
            elif wire_type == 2:  # length-delimited
                length, pos = read_varint(pos)
                if length is None or length < 0 or pos + length > size:
                    break
                fields.append((field_num, "bytes", buf[pos : pos + length]))
                pos += length
            elif wire_type == 5:  # 32-bit
                if pos + 4 > size:
                    break
                fields.append((field_num, "fixed32", buf[pos : pos + 4]))
                pos += 4
            else:  # groups (3/4) are deprecated; stop to avoid desync
                break
        except (IndexError, TypeError):
            break
    return fields


def _safe_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(value, 0)
    if isinstance(value, float):
        return max(int(value), 0)
    return 0


def _extract_gen_tokens(data: bytes) -> Optional[Dict[str, Any]]:
    """Extract model name and token metrics from Antigravity generation metadata blob."""
    if not data:
        return None
    try:
        top = _parse_proto(bytes(data))
        f1_list = [v for fn, wt, v in top if fn == 1]
        if not f1_list:
            return None
        sub = _parse_proto(f1_list[0])
        model_name = _UNKNOWN_MODEL
        for fn, wt, v in sub:
            if fn == 19 and isinstance(v, (bytes, bytearray)):
                try:
                    decoded = bytes(v).decode("utf-8", "ignore").strip()
                except Exception:
                    decoded = ""
                if decoded:
                    model_name = decoded

        in_tokens = 0
        f9_list = [v for fn, wt, v in sub if fn == 9]
        if f9_list:
            f9 = _parse_proto(f9_list[0])
            f10_list = [v for fn, wt, v in f9 if fn == 10]
            if f10_list:
                f10 = _parse_proto(f10_list[0])
                for fn, wt, v in f10:
                    if fn == 1 and wt == "varint":
                        in_tokens = _safe_int(v)

        out_tokens = 0
        cached_tokens = 0
        reasoning_tokens = 0
        f17_list = [v for fn, wt, v in sub if fn == 17]
        if f17_list:
            f17 = _parse_proto(f17_list[0])
            f2_list = [v for fn, wt, v in f17 if fn == 2]
            if f2_list:
                f2 = _parse_proto(f2_list[0])
                for fn, wt, v in f2:
                    if wt != "varint":
                        continue
                    if fn == 1:
                        out_tokens = _safe_int(v)
                    elif fn == 2:
                        cached_tokens = _safe_int(v)
                    elif fn == 3:
                        reasoning_tokens = _safe_int(v)

        if not (in_tokens or out_tokens or cached_tokens or reasoning_tokens):
            return None
        return {
            "model": model_name,
            "input": in_tokens,
            "output": out_tokens,
            "cached": cached_tokens,
            "reasoning": reasoning_tokens,
        }
    except Exception:
        return None


class AntigravityProvider(BaseProvider):
    """Parses ~/.gemini/antigravity-cli session databases (read-only)."""

    def __init__(self, base_dir: Optional[str] = None):
        self.base_dir = base_dir or os.path.expanduser("~/.gemini/antigravity-cli")
        self.conv_dir = os.path.join(self.base_dir, "conversations")
        self.summaries_db = os.path.join(self.base_dir, "conversation_summaries.db")

    @property
    def name(self) -> str:
        return "Antigravity (AGY)"

    def is_available(self) -> bool:
        return os.path.isdir(self.conv_dir)

    @staticmethod
    def _connect_ro(path: str) -> sqlite3.Connection:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _load_summaries(self) -> Dict[str, Dict[str, Any]]:
        sessions_meta: Dict[str, Dict[str, Any]] = {}
        if not os.path.exists(self.summaries_db):
            return sessions_meta
        try:
            with self._connect_ro(self.summaries_db) as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT conversation_id, title, step_count, last_modified_time"
                    " FROM conversation_summaries"
                )
                for row in cur.fetchall():
                    sessions_meta[row[0]] = {
                        "title": row[1],
                        "steps": row[2],
                        "mtime": row[3],
                    }
        except sqlite3.Error:
            pass
        return sessions_meta

    def _is_today(self, mtime: Any, db_file: str) -> bool:
        """True if the conversation was active today (local time)."""
        today = date.today()
        if isinstance(mtime, str) and len(mtime) >= 10:
            # mtime is "YYYY-MM-DD HH:MM:SS..." — compare the date prefix
            # against both local today and UTC today to tolerate TZ skew.
            from datetime import timezone

            utc_today = datetime.now(timezone.utc).date().isoformat()
            if mtime[:10] in (today.isoformat(), utc_today):
                return True
        try:
            return datetime.fromtimestamp(os.stat(db_file).st_mtime).date() == today
        except OSError:
            return False

    def get_report(self, today_only: bool = False) -> Optional[AgentReport]:
        if not self.is_available():
            return None

        sessions_meta = self._load_summaries()
        models_dict: Dict[str, Dict[str, Any]] = {}
        recent_sessions: List[SessionInfo] = []

        for db_file in sorted(glob.glob(os.path.join(self.conv_dir, "*.db"))):
            cid = os.path.splitext(os.path.basename(db_file))[0]
            meta = sessions_meta.get(cid, {})
            mtime = meta.get("mtime", "")

            if today_only and not self._is_today(mtime, db_file):
                continue

            try:
                with self._connect_ro(db_file) as conn:
                    cur = conn.cursor()
                    try:
                        cur.execute("SELECT data FROM gen_metadata")
                    except sqlite3.Error:
                        continue  # unexpected schema — skip file, not the run
                    rows = cur.fetchall()
            except (sqlite3.Error, OSError):
                continue

            if not rows:
                continue

            session_in = session_out = session_reasoning = session_cached = 0
            model_votes: Counter = Counter()
            turns = 0
            for row in rows:
                metrics = _extract_gen_tokens(row[0])
                if not metrics:
                    continue
                m = metrics["model"] or _UNKNOWN_MODEL
                model_votes[m] += 1
                bucket = models_dict.setdefault(
                    m,
                    {
                        "input": 0,
                        "output": 0,
                        "reasoning": 0,
                        "cached": 0,
                        "turns": 0,
                        "sessions": set(),
                    },
                )
                bucket["input"] += metrics["input"]
                bucket["output"] += metrics["output"]
                bucket["reasoning"] += metrics["reasoning"]
                bucket["cached"] += metrics["cached"]
                bucket["turns"] += 1
                bucket["sessions"].add(cid)

                session_in += metrics["input"]
                session_out += metrics["output"]
                session_reasoning += metrics["reasoning"]
                session_cached += metrics["cached"]
                turns += 1

            if session_in or session_out or session_cached:
                # Attribute multi-model sessions to the most frequent model.
                session_model = (
                    model_votes.most_common(1)[0][0] if model_votes else _UNKNOWN_MODEL
                )
                updated = mtime[:19] if isinstance(mtime, str) and mtime else None
                recent_sessions.append(
                    SessionInfo(
                        session_id=cid,
                        title=meta.get("title") or cid[:18],
                        model_id=session_model,
                        input_tokens=session_in,
                        output_tokens=session_out,
                        reasoning_tokens=session_reasoning,
                        cache_read_tokens=session_cached,
                        turn_count=turns,
                        updated_at=updated,
                    )
                )

        models = [
            TokenStats(
                model_id=m,
                input_tokens=stats["input"],
                output_tokens=stats["output"],
                reasoning_tokens=stats["reasoning"],
                cache_read_tokens=stats["cached"],
                turn_count=stats["turns"],
                session_count=len(stats["sessions"]),
            )
            for m, stats in models_dict.items()
        ]

        models.sort(key=lambda x: x.total_tokens, reverse=True)
        # "Recent" means most recently active; fall back to size when the
        # timestamp is missing so undated sessions still surface sensibly.
        recent_sessions.sort(
            key=lambda s: (s.updated_at or "", s.total_tokens), reverse=True
        )
        return AgentReport(agent_name=self.name, models=models, recent_sessions=recent_sessions)
