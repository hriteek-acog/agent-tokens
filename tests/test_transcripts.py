"""Unit tests for the shared transcript/activity helpers."""

import json
import os
import tempfile
import time
import unittest

from agent_tokens.models import SessionInfo
from agent_tokens.providers.transcripts import (
    build_activity_report,
    build_token_report,
    dedupe_chats,
    scan_transcript_dir,
)


def _write(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)


class TestScanTranscriptDir(unittest.TestCase):
    def test_sums_token_fields_and_counts_user_turns(self):
        with tempfile.TemporaryDirectory() as d:
            _write(os.path.join(d, "c.json"), {
                "messages": [
                    {"role": "user", "content": "hi"},
                    {"role": "assistant", "content": "yo"},
                ],
                "usage": {"inputTokens": 100, "outputTokens": 40,
                          "cacheReadInputTokens": 500,
                          "cacheCreationInputTokens": 7,
                          "reasoningOutputTokens": 9},
            })
            chats = scan_transcript_dir(d, False)
            self.assertEqual(len(chats), 1)
            c = chats[0]
            self.assertEqual((c["input"], c["output"], c["cached"],
                              c["cache_write"], c["reasoning"], c["turns"]),
                             (100, 40, 500, 7, 9, 1))

    def test_jsonl_and_malformed_lines(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "c.jsonl")
            with open(p, "w") as f:
                f.write('{"input_tokens": 10}\nnot-json\n{"output_tokens": 5}\n')
            chats = scan_transcript_dir(d, False)
            self.assertEqual(len(chats), 1)
            self.assertEqual(chats[0]["input"], 10)
            self.assertEqual(chats[0]["output"], 5)

    def test_oversize_and_invalid_files_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            big = os.path.join(d, "big.json")
            with open(big, "w") as f:
                f.write("x" * (11 * 1024 * 1024))
            bad = os.path.join(d, "bad.json")
            with open(bad, "w") as f:
                f.write("{oops")
            self.assertEqual(scan_transcript_dir(d, False), [])
            self.assertEqual(scan_transcript_dir("/nonexistent", False), [])

    def test_today_filter_uses_file_mtime(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "c.json")
            _write(p, {"input_tokens": 3})
            ancient = time.time() - 10 * 86400
            os.utime(p, (ancient, ancient))
            self.assertEqual(scan_transcript_dir(d, True), [])
            self.assertEqual(len(scan_transcript_dir(d, False)), 1)

    def test_recursion_bounds_do_not_hang(self):
        with tempfile.TemporaryDirectory() as d:
            doc = cur = {}
            for _ in range(200):
                cur["n"] = {}
                cur = cur["n"]
            cur["input_tokens"] = 5  # buried past _MAX_DEPTH: must not crash
            _write(os.path.join(d, "deep.json"), doc)
            chats = scan_transcript_dir(d, False)
            self.assertEqual(len(chats), 1)


class TestDedupeChats(unittest.TestCase):
    def test_dedupe_and_segment_exclusion(self):
        chats = [
            {"path": "/a/s.json"},
            {"path": "/a/s.json"},
            {"path": "/a/skills/m.json"},
        ]
        out = dedupe_chats(chats, exclude_segments=frozenset({"skills"}))
        self.assertEqual([c["path"] for c in out], ["/a/s.json"])


class TestBuildTokenReport(unittest.TestCase):
    def test_aggregation_and_session_cap(self):
        chats = [
            {"path": f"/x/{i}.json", "input": 10, "output": 5, "cached": 0,
             "cache_write": 0, "reasoning": 0, "turns": 1,
             "mtime": f"2026-09-0{i % 9 + 1} 00:00:00"}
            for i in range(30)
        ]
        rep = build_token_report("Gem", "gemini-cli", chats)
        self.assertEqual(rep.models[0].session_count, 30)
        self.assertEqual(rep.models[0].total_tokens, 30 * 15)
        self.assertEqual(len(rep.recent_sessions), 25)

    def test_empty(self):
        rep = build_token_report("Gem", "gemini-cli", [])
        self.assertEqual(rep.models, [])
        self.assertEqual(rep.recent_sessions, [])


class TestBuildActivityReport(unittest.TestCase):
    def test_orders_and_counts(self):
        sessions = [
            SessionInfo(session_id="a", title="A", model_id="m",
                        updated_at="2026-09-01 00:00:00"),
            SessionInfo(session_id="b", title="B", model_id="m", turn_count=3,
                        updated_at="2026-09-04 00:00:00"),
        ]
        rep = build_activity_report("Cur", "cursor-composer", sessions)
        self.assertEqual(rep.models[0].session_count, 2)
        self.assertEqual(rep.models[0].turn_count, 3)
        self.assertEqual(rep.models[0].total_tokens, 0)
        self.assertEqual(rep.models[0].last_active, "2026-09-04 00:00:00")
        self.assertEqual(rep.recent_sessions[0].session_id, "b")

    def test_empty(self):
        rep = build_activity_report("Cur", "m", [])
        self.assertEqual(rep.models, [])


if __name__ == "__main__":
    unittest.main()
