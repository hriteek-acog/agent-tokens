"""Provider for extracting token usage from Google Antigravity (AGY) sessions."""

import glob
import os
import sqlite3
from datetime import datetime, date
from typing import Optional, Dict, Any, List

from agent_tokens.models import AgentReport, TokenStats, SessionInfo
from agent_tokens.providers.base import BaseProvider


def _parse_proto(buf: bytes) -> List[tuple]:
    """Lightweight pure-Python protobuf field decoder."""
    pos = 0
    fields = []
    def read_varint(p):
        res = 0
        shift = 0
        while p < len(buf):
            b = buf[p]
            p += 1
            res |= (b & 0x7F) << shift
            if not (b & 0x80):
                break
            shift += 7
        return res, p

    while pos < len(buf):
        try:
            tag, pos = read_varint(pos)
            field_num = tag >> 3
            wire_type = tag & 0x7
            if wire_type == 0:
                val, pos = read_varint(pos)
                fields.append((field_num, "varint", val))
            elif wire_type == 2:
                length, pos = read_varint(pos)
                val = buf[pos : pos + length]
                pos += length
                fields.append((field_num, "bytes", val))
            else:
                break
        except Exception:
            break
    return fields


def _extract_gen_tokens(data: bytes) -> Optional[Dict[str, Any]]:
    """Extract model name and token metrics from Antigravity generation metadata blob."""
    try:
        top = _parse_proto(data)
        f1_list = [v for fn, wt, v in top if fn == 1]
        if not f1_list:
            return None
        sub = _parse_proto(f1_list[0])
        model_name = "gemini"
        for fn, wt, v in sub:
            if fn == 19:
                try:
                    model_name = v.decode("utf-8", "ignore")
                except Exception:
                    pass

        in_tokens = 0
        f9_list = [v for fn, wt, v in sub if fn == 9]
        if f9_list:
            f9 = _parse_proto(f9_list[0])
            f10_list = [v for fn, wt, v in f9 if fn == 10]
            if f10_list:
                f10 = _parse_proto(f10_list[0])
                for fn, wt, v in f10:
                    if fn == 1:
                        in_tokens = v

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
                    if fn == 1:
                        out_tokens = v
                    if fn == 2:
                        cached_tokens = v
                    if fn == 3:
                        reasoning_tokens = v

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
    """Parses ~/.gemini/antigravity-cli session databases."""

    def __init__(self, base_dir: Optional[str] = None):
        self.base_dir = base_dir or os.path.expanduser("~/.gemini/antigravity-cli")
        self.conv_dir = os.path.join(self.base_dir, "conversations")
        self.summaries_db = os.path.join(self.base_dir, "conversation_summaries.db")

    @property
    def name(self) -> str:
        return "Antigravity (AGY)"

    def is_available(self) -> bool:
        return os.path.exists(self.conv_dir)

    def get_report(self, today_only: bool = False) -> Optional[AgentReport]:
        if not self.is_available():
            return None

        # Load session summaries
        sessions_meta = {}
        if os.path.exists(self.summaries_db):
            try:
                conn = sqlite3.connect(self.summaries_db)
                cur = conn.cursor()
                cur.execute(
                    "SELECT conversation_id, title, step_count, last_modified_time FROM conversation_summaries"
                )
                for cid, title, steps, mtime in cur.fetchall():
                    sessions_meta[cid] = {"title": title, "steps": steps, "mtime": mtime}
                conn.close()
            except Exception:
                pass

        today_iso = date.today().isoformat()
        models_dict = {}
        recent_sessions = []

        for db_file in glob.glob(os.path.join(self.conv_dir, "*.db")):
            cid = os.path.splitext(os.path.basename(db_file))[0]
            meta = sessions_meta.get(cid, {})
            mtime = meta.get("mtime", "")

            if today_only and mtime and not mtime.startswith(today_iso):
                # If modified before today, check file mtime as backup
                st = os.stat(db_file)
                if datetime.fromtimestamp(st.st_mtime).date() != date.today():
                    continue

            session_in = 0
            session_out = 0
            session_reasoning = 0
            session_cached = 0
            session_model = "gemini"

            try:
                conn = sqlite3.connect(db_file)
                cur = conn.cursor()
                cur.execute("SELECT idx, data FROM gen_metadata")
                rows = cur.fetchall()
                if not rows:
                    conn.close()
                    continue

                for idx, data in rows:
                    metrics = _extract_gen_tokens(data)
                    if not metrics:
                        continue
                    m = metrics["model"]
                    session_model = m
                    if m not in models_dict:
                        models_dict[m] = {
                            "input": 0,
                            "output": 0,
                            "reasoning": 0,
                            "cached": 0,
                            "turns": 0,
                            "sessions": set(),
                        }
                    models_dict[m]["input"] += metrics["input"]
                    models_dict[m]["output"] += metrics["output"]
                    models_dict[m]["reasoning"] += metrics["reasoning"]
                    models_dict[m]["cached"] += metrics["cached"]
                    models_dict[m]["turns"] += 1
                    models_dict[m]["sessions"].add(cid)

                    session_in += metrics["input"]
                    session_out += metrics["output"]
                    session_reasoning += metrics["reasoning"]
                    session_cached += metrics["cached"]

                conn.close()

                if session_in or session_out:
                    recent_sessions.append(
                        SessionInfo(
                            session_id=cid,
                            title=meta.get("title") or cid[:18],
                            model_id=session_model,
                            input_tokens=session_in,
                            output_tokens=session_out,
                            reasoning_tokens=session_reasoning,
                            cache_read_tokens=session_cached,
                            updated_at=mtime[:19] if mtime else None,
                        )
                    )
            except Exception:
                pass

        models = []
        for m, stats in models_dict.items():
            models.append(
                TokenStats(
                    model_id=m,
                    input_tokens=stats["input"],
                    output_tokens=stats["output"],
                    reasoning_tokens=stats["reasoning"],
                    cache_read_tokens=stats["cached"],
                    turn_count=stats["turns"],
                    session_count=len(stats["sessions"]),
                )
            )

        models.sort(key=lambda x: x.total_tokens, reverse=True)
        recent_sessions.sort(key=lambda x: x.total_tokens, reverse=True)
        return AgentReport(agent_name=self.name, models=models, recent_sessions=recent_sessions)
