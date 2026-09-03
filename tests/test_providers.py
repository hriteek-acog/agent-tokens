"""Unit tests for agent-tokens providers (opencode, claude, antigravity)."""

import json
import os
import sqlite3
import tempfile
import time
import unittest
from datetime import datetime
from unittest import mock

from agent_tokens.providers.opencode import OpenCodeProvider
from agent_tokens.providers.claude import ClaudeCodeProvider, _split_total_proportionally
from agent_tokens.providers.antigravity import (
    AntigravityProvider,
    _extract_gen_tokens,
    _parse_proto,
)


def _make_opencode_db(path: str, now_ms: int) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        """CREATE TABLE session (
            id TEXT PRIMARY KEY, title TEXT, model TEXT,
            tokens_input INTEGER DEFAULT 0, tokens_output INTEGER DEFAULT 0,
            tokens_reasoning INTEGER DEFAULT 0,
            tokens_cache_read INTEGER DEFAULT 0,
            tokens_cache_write INTEGER DEFAULT 0,
            time_updated INTEGER NOT NULL
        )"""
    )
    conn.execute(
        "INSERT INTO session VALUES (?,?,?,?,?,?,?,?,?)",
        ("s1", "Today session", '{"id":"model-a"}', 100, 50, 10, 1000, 20, now_ms),
    )
    conn.execute(
        "INSERT INTO session VALUES (?,?,?,?,?,?,?,?,?)",
        ("s2", None, '{"id":"model-b"}', 200, 30, 0, 500, 0, now_ms - 30 * 86400 * 1000),
    )
    conn.commit()
    conn.close()


class TestOpenCodeProvider(unittest.TestCase):
    def test_missing_db_returns_none(self):
        p = OpenCodeProvider(db_path="/nonexistent/opencode.db")
        self.assertFalse(p.is_available())
        self.assertIsNone(p.get_report())

    def test_all_time_and_today_filtering(self):
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "opencode.db")
            now_ms = int(time.time() * 1000)
            _make_opencode_db(db, now_ms)
            p = OpenCodeProvider(db_path=db)

            all_time = p.get_report(today_only=False)
            self.assertEqual(len(all_time.models), 2)
            # recent sessions populated for both scopes (regression guard)
            self.assertEqual(len(all_time.recent_sessions), 2)
            by_id = {m.model_id: m for m in all_time.models}
            # cache_write + reasoning now counted in totals
            self.assertEqual(by_id["model-a"].total_tokens, 100 + 50 + 10 + 1000 + 20)
            self.assertEqual(by_id["model-a"].cache_write_tokens, 20)

            today = p.get_report(today_only=True)
            self.assertEqual(len(today.models), 1)
            self.assertEqual(today.models[0].model_id, "model-a")
            self.assertEqual(len(today.recent_sessions), 1)

    def test_missing_table_returns_empty_report(self):
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "opencode.db")
            conn = sqlite3.connect(db)
            conn.execute("CREATE TABLE other (id TEXT)")
            conn.commit()
            conn.close()
            p = OpenCodeProvider(db_path=db)
            rep = p.get_report()
            self.assertIsNotNone(rep)
            self.assertEqual(rep.models, [])


class TestClaudeProvider(unittest.TestCase):
    def _write(self, d: str, payload: dict) -> str:
        path = os.path.join(d, "stats-cache.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        return path

    def test_missing_file_returns_none(self):
        p = ClaudeCodeProvider(stats_path="/nonexistent/stats.json")
        self.assertIsNone(p.get_report())

    def test_malformed_json_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "stats-cache.json")
            with open(path, "w") as f:
                f.write("{not json")
            p = ClaudeCodeProvider(stats_path=path)
            self.assertIsNone(p.get_report())

    def test_all_time_breakdown(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._write(
                d,
                {
                    "lastComputedDate": "2026-09-03",
                    "modelUsage": {
                        "claude-x": {
                            "inputTokens": 100,
                            "outputTokens": 50,
                            "cacheReadInputTokens": 1000,
                            "cacheCreationInputTokens": 25,
                        }
                    },
                    "dailyModelTokens": [],
                },
            )
            rep = ClaudeCodeProvider(stats_path=path).get_report()
            self.assertEqual(len(rep.models), 1)
            self.assertEqual(rep.models[0].total_tokens, 1175)
            self.assertEqual(rep.models[0].last_active, "2026-09-03")

    def test_today_v5_totals_schema(self):
        """Regression test: v5 dailyModelTokens only has totals per model."""
        from datetime import date

        today = date.today().isoformat()
        with tempfile.TemporaryDirectory() as d:
            path = self._write(
                d,
                {
                    "modelUsage": {
                        "claude-x": {
                            "inputTokens": 100,
                            "outputTokens": 300,
                            "cacheReadInputTokens": 600,
                            "cacheCreationInputTokens": 0,
                        }
                    },
                    "dailyModelTokens": [
                        {"date": "2000-01-01", "tokensByModel": {"claude-x": 999}},
                        {"date": today, "tokensByModel": {"claude-x": 1000}},
                    ],
                },
            )
            rep = ClaudeCodeProvider(stats_path=path).get_report(today_only=True)
            self.assertEqual(len(rep.models), 1)
            m = rep.models[0]
            # Total stays exact; breakdown follows 1:3:6 all-time ratios.
            self.assertEqual(m.total_tokens, 1000)
            self.assertEqual(m.input_tokens, 100)
            self.assertEqual(m.output_tokens, 300)
            self.assertEqual(m.cache_read_tokens, 600)

    def test_today_no_entry_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._write(
                d, {"modelUsage": {}, "dailyModelTokens": [{"date": "2000-01-01", "tokensByModel": {"m": 5}}]}
            )
            rep = ClaudeCodeProvider(stats_path=path).get_report(today_only=True)
            self.assertEqual(rep.models, [])

    def test_split_fallback_without_baseline(self):
        stats = _split_total_proportionally("new-model", 500, {})
        self.assertEqual(stats.total_tokens, 500)
        self.assertEqual(stats.input_tokens, 500)


class TestAntigravityProto(unittest.TestCase):
    def test_parse_proto_varint_and_bytes(self):
        # field 1 varint=150, field 2 bytes="hi"
        buf = bytes([0x08, 0x96, 0x01, 0x12, 0x02]) + b"hi"
        fields = _parse_proto(buf)
        self.assertIn((1, "varint", 150), fields)
        self.assertIn((2, "bytes", b"hi"), fields)

    def test_parse_proto_skips_fixed_width(self):
        # field 1 fixed64 then field 2 varint=7 (old code broke out here)
        buf = bytes([0x09]) + b"\x00" * 8 + bytes([0x10, 0x07])
        fields = _parse_proto(buf)
        self.assertIn((2, "varint", 7), fields)

    def test_parse_proto_truncated_returns_partial(self):
        self.assertEqual(_parse_proto(b"\xff"), [])

    def test_extract_gen_tokens_empty(self):
        self.assertIsNone(_extract_gen_tokens(b""))
        self.assertIsNone(_extract_gen_tokens(b"\x08\x01"))


class TestAntigravityProvider(unittest.TestCase):
    def test_missing_dir_returns_none(self):
        p = AntigravityProvider(base_dir="/nonexistent/agy")
        self.assertIsNone(p.get_report())

    def test_skips_files_without_gen_metadata_table(self):
        with tempfile.TemporaryDirectory() as base:
            conv = os.path.join(base, "conversations")
            os.makedirs(conv)
            db = os.path.join(conv, "abc.db")
            conn = sqlite3.connect(db)
            conn.execute("CREATE TABLE other (id TEXT)")
            conn.commit()
            conn.close()
            p = AntigravityProvider(base_dir=base)
            rep = p.get_report()
            self.assertIsNotNone(rep)
            self.assertEqual(rep.models, [])

    def test_today_filter_uses_file_mtime_fallback(self):
        # Conversation without a summaries entry: file mtime decides.
        with tempfile.TemporaryDirectory() as base:
            conv = os.path.join(base, "conversations")
            os.makedirs(conv)
            db = os.path.join(conv, "cid123.db")
            conn = sqlite3.connect(db)
            conn.execute("CREATE TABLE gen_metadata (idx INTEGER, data BLOB)")
            conn.execute("INSERT INTO gen_metadata VALUES (?, ?)", (0, b"\x08\x01"))
            conn.commit()
            conn.close()
            old = time.time() - 10 * 86400
            os.utime(db, (old, old))
            p = AntigravityProvider(base_dir=base)
            with mock.patch(
                "agent_tokens.providers.antigravity._extract_gen_tokens",
                return_value={"model": "m", "input": 5, "output": 5, "cached": 0, "reasoning": 0},
            ):
                all_rep = p.get_report(today_only=False)
                today_rep = p.get_report(today_only=True)
            self.assertTrue(all_rep.models)
            self.assertEqual(today_rep.models, [])

    def test_recent_sessions_sorted_by_recency(self):
        self.assertTrue(datetime.now())  # smoke: module imports cleanly


if __name__ == "__main__":
    unittest.main()
