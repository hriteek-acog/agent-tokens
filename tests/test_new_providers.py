"""Unit tests for the 9 new agent providers (12-agent expansion)."""

import json
import os
import sqlite3
import tempfile
import time
import unittest

from agent_tokens.providers.codex import CodexProvider, _parse_rollout
from agent_tokens.providers.copilot import CopilotProvider, _parse_harness_events
from agent_tokens.providers.cursor import CursorProvider
from agent_tokens.providers.gemini_cli import GeminiCliProvider
from agent_tokens.providers.qwen import QwenProvider
from agent_tokens.providers.pi import PiProvider
from agent_tokens.providers.deepseek import DeepSeekProvider
from agent_tokens.providers.cline import ClineProvider
from agent_tokens.providers.cursor import CursorProvider as _CursorDupCheck
from agent_tokens.providers.windsurf import WindsurfProvider


def _write_jsonl(path, records):
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


class TestCodexProvider(unittest.TestCase):
    def _rollout(self, path, model="gpt-5.6-terra", total=None, ts="2026-09-04T05:00:00.000Z"):
        total = total or {
            "input_tokens": 1000, "cached_input_tokens": 400,
            "cache_write_input_tokens": 10, "output_tokens": 200,
            "reasoning_output_tokens": 50, "total_tokens": 1250,
        }
        _write_jsonl(path, [
            {"type": "session_meta",
             "payload": {"timestamp": ts, "cwd": "/tmp/proj"}},
            {"type": "turn_context", "payload": {"model": model}},
            {"type": "event_msg",
             "payload": {"type": "token_count",
                         "info": {"total_token_usage": total}}},
        ])

    def test_new_schema_splits_cached_input(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "rollout-1.jsonl")
            self._rollout(p)
            rep = CodexProvider(base_dir=d).get_report()
            self.assertEqual(len(rep.models), 1)
            m = rep.models[0]
            self.assertEqual(m.model_id, "gpt-5.6-terra")
            self.assertEqual(m.input_tokens, 600)  # 1000 - 400 cached
            self.assertEqual(m.cache_read_tokens, 400)
            self.assertEqual(m.total_tokens, 600 + 200 + 50 + 400 + 10)
            self.assertEqual(m.session_count, 1)
            self.assertEqual(len(rep.recent_sessions), 1)
            self.assertEqual(rep.recent_sessions[0].title, "proj")

    def test_old_schema_lump_total_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "rollout-old.jsonl")
            _write_jsonl(p, [
                {"type": "session_meta",
                 "payload": {"timestamp": "2026-01-01T00:00:00.000Z", "cwd": "/tmp/o"}},
                {"type": "event_msg",
                 "payload": {"type": "token_count",
                             "info": {"total_token_usage": {"total_tokens": 500}}}},
            ])
            rep = CodexProvider(base_dir=d).get_report()
            self.assertEqual(rep.models[0].total_tokens, 500)

    def test_sessions_without_tokens_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "rollout-empty.jsonl")
            _write_jsonl(p, [{"type": "session_meta", "payload": {}}])
            self.assertIsNone(_parse_rollout(p))
            rep = CodexProvider(base_dir=d).get_report()
            self.assertEqual(rep.models, [])

    def test_missing_dir_returns_none(self):
        self.assertIsNone(CodexProvider(base_dir="/nonexistent").get_report())

    def test_today_filter(self):
        with tempfile.TemporaryDirectory() as d:
            fresh = os.path.join(d, "rollout-fresh.jsonl")
            self._rollout(fresh)
            old = os.path.join(d, "rollout-old.jsonl")
            self._rollout(old, ts="2000-01-01T00:00:00.000Z")
            ancient = time.time() - 10 * 86400
            os.utime(old, (ancient, ancient))
            rep = CodexProvider(base_dir=d).get_report(today_only=True)
            self.assertEqual(len(rep.models), 1)
            self.assertEqual(rep.models[0].session_count, 1)


class TestCopilotProvider(unittest.TestCase):
    def _harness(self, root, sid="sid1", model="gpt-5", tokens=1000):
        sdir = os.path.join(root, sid)
        os.makedirs(sdir)
        _write_jsonl(os.path.join(sdir, "events.jsonl"), [
            {"type": "session.start",
             "data": {"selectedModel": model, "startTime": "2026-09-04T01:00:00.000Z",
                      "context": {"cwd": "/tmp/repo", "repository": "o/r"}}},
            {"type": "assistant.turn_end", "data": {"turnId": "0"}},
            {"type": "session.shutdown",
             "timestamp": "2026-09-04T01:05:00.000Z",
             "data": {"currentTokens": tokens}},
        ])
        return sdir

    def _chat_db(self, path):
        con = sqlite3.connect(path)
        con.execute(
            "CREATE TABLE sessions (id TEXT PRIMARY KEY, cwd TEXT, repository TEXT,"
            " summary TEXT, agent_name TEXT, created_at TEXT, updated_at TEXT)"
        )
        con.execute("CREATE TABLE turns (id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    " session_id TEXT, turn_index INTEGER, user_message TEXT,"
                    " assistant_response TEXT, timestamp TEXT)")
        con.execute(
            "INSERT INTO sessions VALUES (?,?,?,?,?,?,?)",
            ("chat1", "/tmp/x", "o/x", "Fix bug", "Inline Chat",
             "2026-09-04T02:00:00.000Z", "2026-09-04T02:01:00.000Z"),
        )
        con.execute(
            "INSERT INTO turns (session_id, turn_index) VALUES (?,?)", ("chat1", 0)
        )
        con.commit()
        con.close()

    def test_harness_and_chat_combined(self):
        with tempfile.TemporaryDirectory() as d:
            hdir = os.path.join(d, "state")
            os.makedirs(hdir)
            self._harness(hdir)
            db = os.path.join(d, "session-store.db")
            self._chat_db(db)
            rep = CopilotProvider(harness_dir=hdir, chat_db=db).get_report()
            by_id = {m.model_id: m for m in rep.models}
            self.assertEqual(by_id["gpt-5"].input_tokens, 1000)
            self.assertEqual(by_id["gpt-5"].turn_count, 1)
            self.assertEqual(by_id["Inline Chat"].session_count, 1)
            self.assertEqual(len(rep.recent_sessions), 2)

    def test_model_change_uses_latest(self):
        with tempfile.TemporaryDirectory() as d:
            sdir = os.path.join(d, "s1")
            os.makedirs(sdir)
            _write_jsonl(os.path.join(sdir, "events.jsonl"), [
                {"type": "session.start", "data": {"selectedModel": "old"}},
                {"type": "session.model_change", "data": {"newModel": "new"}},
                {"type": "session.shutdown", "data": {"currentTokens": 10}},
            ])
            rep = CopilotProvider(harness_dir=d, chat_db="/nonexistent.db").get_report()
            self.assertEqual(rep.models[0].model_id, "new")

    def test_unavailable(self):
        p = CopilotProvider(harness_dir="/nonexistent", chat_db="/nonexistent.db")
        self.assertFalse(p.is_available())
        self.assertIsNone(p.get_report())

    def test_harness_without_start_ignored(self):
        self.assertIsNone(_parse_harness_events("/nonexistent"))
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "e.jsonl")
            _write_jsonl(p, [{"type": "assistant.turn_end", "data": {}}])
            self.assertIsNone(_parse_harness_events(p))


class TestCursorProvider(unittest.TestCase):
    def test_workspace_activity(self):
        with tempfile.TemporaryDirectory() as root:
            for name, folder in (("aaa", "file:///tmp/myproj"), ("bbb", None)):
                wdir = os.path.join(root, name)
                os.makedirs(wdir)
                if folder:
                    with open(os.path.join(wdir, "workspace.json"), "w") as f:
                        json.dump({"folder": folder}, f)
            rep = CursorProvider(storage_dir=root).get_report()
            self.assertEqual(rep.models[0].session_count, 2)
            titles = {s.title for s in rep.recent_sessions}
            self.assertIn("myproj", titles)

    def test_missing_returns_none(self):
        self.assertIsNone(CursorProvider(storage_dir="/nonexistent").get_report())

    def test_registry_import_sanity(self):
        self.assertIs(_CursorDupCheck, CursorProvider)


class TestGeminiQwenProviders(unittest.TestCase):
    def _chat(self, path):
        with open(path, "w") as f:
            json.dump(
                {"messages": [
                    {"role": "user", "content": "hi"},
                    {"role": "model", "content": "hello",
                     "input_tokens": 100, "output_tokens": 50},
                ]}, f)

    def test_gemini_scan(self):
        with tempfile.TemporaryDirectory() as d:
            self._chat(os.path.join(d, "chat-1.json"))
            rep = GeminiCliProvider(tmp_dir=d).get_report()
            self.assertEqual(rep.models[0].input_tokens, 100)
            self.assertEqual(rep.models[0].output_tokens, 50)
            self.assertEqual(rep.models[0].turn_count, 1)

    def test_qwen_scan(self):
        with tempfile.TemporaryDirectory() as d:
            self._chat(os.path.join(d, "chat-1.json"))
            rep = QwenProvider(tmp_dir=d).get_report()
            self.assertEqual(rep.models[0].model_id, "qwen-code")
            self.assertEqual(rep.models[0].total_tokens, 150)

    def test_unavailable(self):
        self.assertIsNone(GeminiCliProvider(tmp_dir="/nonexistent").get_report())
        self.assertIsNone(QwenProvider(tmp_dir="/nonexistent").get_report())


class TestPiDeepSeekProviders(unittest.TestCase):
    def test_pi_skips_skills_metadata(self):
        with tempfile.TemporaryDirectory() as base:
            skills = os.path.join(base, "skills", "demo")
            os.makedirs(skills)
            with open(os.path.join(skills, "metadata.json"), "w") as f:
                json.dump({"name": "demo"}, f)
            rep = PiProvider(base_dir=base).get_report()
            self.assertEqual(rep.models, [])
            self.assertEqual(rep.recent_sessions, [])

    def test_pi_reads_session_file(self):
        with tempfile.TemporaryDirectory() as base:
            sdir = os.path.join(base, "sessions")
            os.makedirs(sdir)
            with open(os.path.join(sdir, "s1.json"), "w") as f:
                json.dump({"input_tokens": 10, "output_tokens": 5}, f)
            rep = PiProvider(base_dir=base).get_report()
            self.assertEqual(rep.models[0].total_tokens, 15)

    def test_deepseek_multi_root(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            for d in (a, b):
                with open(os.path.join(d, "s.json"), "w") as f:
                    json.dump({"input_tokens": 7}, f)
            rep = DeepSeekProvider(base_dirs=[a, b]).get_report()
            self.assertEqual(rep.models[0].input_tokens, 14)

    def test_unavailable(self):
        self.assertIsNone(PiProvider(base_dir="/nonexistent").get_report())
        self.assertIsNone(DeepSeekProvider(base_dirs=["/nonexistent"]).get_report())


class TestClineProvider(unittest.TestCase):
    def _task(self, root, tid="t1", hist=None, meta=None):
        tdir = os.path.join(root, tid)
        os.makedirs(tdir)
        with open(os.path.join(tdir, "api_conversation_history.json"), "w") as f:
            json.dump(hist or [], f)
        if meta:
            with open(os.path.join(tdir, "task_metadata.json"), "w") as f:
                json.dump(meta, f)
        return tdir

    def test_sums_usage_and_model(self):
        with tempfile.TemporaryDirectory() as root:
            self._task(root, hist=[
                {"role": "user", "content": "hi"},
                {"role": "assistant", "tokensIn": 100, "tokensOut": 50,
                 "cacheReads": 1000, "cacheWrites": 20},
            ], meta={"apiModelId": "claude-x", "taskName": "Do thing"})
            rep = ClineProvider(task_roots=[root]).get_report()
            m = rep.models[0]
            self.assertEqual(m.model_id, "claude-x")
            self.assertEqual(m.input_tokens, 100)
            self.assertEqual(m.cache_read_tokens, 1000)
            self.assertEqual(m.turn_count, 1)
            self.assertEqual(rep.recent_sessions[0].title, "Do thing")

    def test_task_without_usage_still_counts(self):
        with tempfile.TemporaryDirectory() as root:
            self._task(root, hist=[{"role": "user"}])
            rep = ClineProvider(task_roots=[root]).get_report()
            self.assertEqual(rep.models[0].session_count, 1)
            self.assertEqual(rep.models[0].total_tokens, 0)

    def test_unavailable(self):
        self.assertIsNone(ClineProvider(task_roots=["/nonexistent"]).get_report())
        self.assertFalse(ClineProvider(task_roots=["/nonexistent"]).is_available())


class TestWindsurfProvider(unittest.TestCase):
    def test_chat_state_counts(self):
        with tempfile.TemporaryDirectory() as d:
            for n in ("codeium_chat_state_file_tmp_proj.pb", "other.pb"):
                with open(os.path.join(d, n), "wb") as f:
                    f.write(b"\x00\x01")
            rep = WindsurfProvider(state_dir=d).get_report()
            self.assertEqual(rep.models[0].session_count, 2)
            titles = {s.title for s in rep.recent_sessions}
            self.assertTrue(any("tmp proj" in t for t in titles))

    def test_today_filter(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.pb")
            with open(p, "wb") as f:
                f.write(b"x")
            ancient = time.time() - 10 * 86400
            os.utime(p, (ancient, ancient))
            rep = WindsurfProvider(state_dir=d).get_report(today_only=True)
            self.assertEqual(rep.models, [])

    def test_unavailable(self):
        self.assertIsNone(WindsurfProvider(state_dir="/nonexistent").get_report())


if __name__ == "__main__":
    unittest.main()
