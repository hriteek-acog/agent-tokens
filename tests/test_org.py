"""Tests for identity, sync payloads, CLI org flags, and the server."""

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from agent_tokens import identity as ident
from agent_tokens import sync as syncmod
from agent_tokens.cli import main
from agent_tokens.models import AgentReport, TokenStats


def _report(name="Codex", total_in=1000):
    return AgentReport(
        agent_name=name,
        models=[TokenStats(model_id="m1", input_tokens=total_in, session_count=2)],
    )


class TestIdentity(unittest.TestCase):
    def test_email_validation(self):
        self.assertEqual(ident.validate_email("Hriteek@aganitha.ai"), "hriteek@aganitha.ai")
        with self.assertRaises(ValueError):
            ident.validate_email("not-an-email")
        with self.assertRaises(ValueError):
            ident.validate_email("user@gmail.com")

    def test_username_from_email(self):
        self.assertEqual(ident.username_from_email("First.Last@aganitha.ai"), "first.last")
        with self.assertRaises(ValueError):
            ident.username_from_email("@@aganitha.ai")

    def test_role_validation(self):
        self.assertEqual(ident.validate_role("Engineering"), "engineering")
        with self.assertRaises(ValueError):
            ident.validate_role("ceo")

    def test_save_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "config.json"
            ident.save_identity(ident.Identity("hriteek", "hriteek@aganitha.ai", "engineering", True), p)
            loaded = ident.load_identity(p)
            self.assertEqual(loaded.username, "hriteek")
            self.assertTrue(loaded.verified)

    def test_onboard_persists(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "c.json"
            with mock.patch.object(ident, "config_path", return_value=p):
                got = ident.onboard("hriteek@aganitha.ai", "research")
            self.assertEqual(got.username, "hriteek")
            self.assertTrue(p.exists())

    def test_ldap_group_mapping(self):
        self.assertEqual(ident.ldap_group_to_role(["Engineering", "docker"]), "engineering")
        self.assertEqual(ident.ldap_group_to_role(["Whatever"]), "other")


class TestSync(unittest.TestCase):
    def test_build_and_verify(self):
        payload = syncmod.build_snapshot(
            "hriteek", "hriteek@aganitha.ai", "engineering",
            [_report("Codex", 1000), _report("Claude Code", 500)],
            client_version="1.2.0",
        )
        self.assertEqual(payload["total_tokens"], 1500)
        self.assertTrue(syncmod.verify_snapshot(payload))
        payload["total_tokens"] = 999999
        self.assertFalse(syncmod.verify_snapshot(payload))

    def test_sync_https_success(self):
        payload = syncmod.build_snapshot("u", "u@aganitha.ai", "other", [_report()])
        with mock.patch.object(syncmod, "post_snapshot", return_value='{"ok": true}') as m:
            res = syncmod.sync_snapshot(payload, server_url="http://x")
        self.assertEqual(res["transport"], "https")
        m.assert_called_once()

    def test_sync_falls_back_to_ssh(self):
        payload = syncmod.build_snapshot("u", "u@aganitha.ai", "other", [_report()])
        with mock.patch.object(syncmod, "post_snapshot", side_effect=RuntimeError("down")):
            with mock.patch.object(syncmod, "ssh_drop_snapshot", return_value="/r/u.json") as s:
                res = syncmod.sync_snapshot(payload, server_url="http://x")
        self.assertEqual(res["transport"], "ssh-drop")
        s.assert_called_once()

    def test_post_rejects_login_html(self):
        """own3 proxy 302s anon POSTs to the LDAP login page — HTML must not
        count as success or sync would silently drop data."""
        import io as _io

        payload = syncmod.build_snapshot("u", "u@aganitha.ai", "other", [_report()])

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b"<html><head><title>Login</title></head></html>"

        with mock.patch.object(syncmod.urllib.request, "urlopen", return_value=_Resp()):
            with self.assertRaises(RuntimeError):
                syncmod.post_snapshot(payload, server_url="http://x")


class TestCLIOrg(unittest.TestCase):
    def setUp(self):
        # Same guard as test_cli: main() must never sync from unit tests.
        self._env = mock.patch.dict(os.environ, {"AGENT_TOKENS_NO_SYNC": "1"})
        self._env.start()

    def tearDown(self):
        self._env.stop()

    def test_me_no_identity(self):
        with mock.patch("agent_tokens.identity.load_identity", return_value=None):
            out = io.StringIO()
            with redirect_stdout(out):
                rc = main(["--me"])
        self.assertEqual(rc, 1)

    def test_onboard_requires_args(self):
        err = io.StringIO()
        with redirect_stderr(err):
            rc = main(["--onboard"])
        self.assertEqual(rc, 2)

    def test_normal_run_syncs_best_effort(self):
        # Not onboarded -> silent skip; display still works.
        stub = _report("OpenCode", 10)
        with mock.patch("agent_tokens.cli.ALL_PROVIDERS", (mock.MagicMock(),)):
            with mock.patch("agent_tokens.identity.load_identity", return_value=None):
                with mock.patch("agent_tokens.cli.collect_reports", return_value=[stub]):
                    out = io.StringIO()
                    with redirect_stdout(out):
                        rc = main(["--json", "--no-sync"])
        self.assertEqual(rc, 0)


class TestServer(unittest.TestCase):

    def test_ingest_and_leaderboard(self):
        import server.app as appmod

        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            with mock.patch.object(appmod, "DATA_DIR", data), \
                 mock.patch.object(appmod, "DB_PATH", data / "leaderboard.db"), \
                 mock.patch.object(appmod, "LEDGER_PATH", data / "ledger.jsonl"), \
                 mock.patch.object(appmod, "USERS_JSON", data / "users.json"):
                p1 = syncmod.build_snapshot("alice", "alice@aganitha.ai", "engineering", [_report("Codex", 1000)])
                r1 = appmod.ingest_snapshot(p1)
                self.assertTrue(r1["ok"])
                # Replay safe: same checksum dedupes.
                r2 = appmod.ingest_snapshot(p1)
                self.assertTrue(r2.get("deduped"))
                # Tampered body rejected.
                bad = dict(p1)
                bad["total_tokens"] = 10**12
                with self.assertRaises(ValueError):
                    appmod.ingest_snapshot(bad)
                # Owner hint (SSH UID) wins over body username.
                p3 = syncmod.build_snapshot("mallory", "m@aganitha.ai", "other", [_report("Codex", 5)])
                r3 = appmod.ingest_snapshot(p3, owner_hint="bob")
                self.assertTrue(r3["ok"])
                lb = appmod.leaderboard("daily")
                names = [u["username"] for u in lb["users"]]
                self.assertIn("alice", names)
                self.assertIn("bob", names)
                self.assertNotIn("mallory", names)
                self.assertTrue(lb["harnesses"])

    def test_role_override_wins(self):
        import server.app as appmod

        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            (data / "users.json").write_text(json.dumps({"alice": "research"}))
            with mock.patch.object(appmod, "DATA_DIR", data), \
                 mock.patch.object(appmod, "DB_PATH", data / "leaderboard.db"), \
                 mock.patch.object(appmod, "LEDGER_PATH", data / "ledger.jsonl"), \
                 mock.patch.object(appmod, "USERS_JSON", data / "users.json"):
                p = syncmod.build_snapshot("alice", "a@aganitha.ai", "engineering", [_report()])
                appmod.ingest_snapshot(p)
                lb = appmod.leaderboard("daily")
                self.assertEqual(lb["users"][0]["role"], "research")

    def test_windows_delta_harness_and_models(self):
        """Harness/model boards must follow the selected window (daily vs weekly)."""
        import datetime as _dt

        import server.app as appmod

        def _reps(codex, claude):
            return [
                AgentReport(agent_name="Codex", models=[TokenStats(model_id="gpt-5", input_tokens=codex, session_count=1)]),
                AgentReport(agent_name="Claude Code", models=[TokenStats(model_id="opus", input_tokens=claude, session_count=1)]),
            ]

    def _patched_app(self, appmod, data):
        return (mock.patch.object(appmod, "DATA_DIR", data),
                mock.patch.object(appmod, "DB_PATH", data / "leaderboard.db"),
                mock.patch.object(appmod, "LEDGER_PATH", data / "ledger.jsonl"),
                mock.patch.object(appmod, "USERS_JSON", data / "users.json"))

    def test_windows_delta_harness_and_models(self):
        """Daily deltas follow the window. The 2-day-old baseline is pre-today
        on every weekday, so this is deterministic by construction."""
        import datetime as _dt

        import server.app as appmod

        def _reps(codex, claude):
            return [
                AgentReport(agent_name="Codex", models=[TokenStats(model_id="gpt-5", input_tokens=codex, session_count=1)]),
                AgentReport(agent_name="Claude Code", models=[TokenStats(model_id="opus", input_tokens=claude, session_count=1)]),
            ]

        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            patches = self._patched_app(appmod, data)
            for p in patches:
                p.start()
            try:
                now = _dt.datetime.now(_dt.timezone.utc)
                old = syncmod.build_snapshot("a", "a@aganitha.ai", "engineering", _reps(1000, 1000))
                old["collected_at"] = (now - _dt.timedelta(days=2)).isoformat()
                old["checksum"] = syncmod.checksum_of(old)
                new = syncmod.build_snapshot("a", "a@aganitha.ai", "engineering", _reps(3000, 1500))
                new["collected_at"] = (now - _dt.timedelta(hours=1)).isoformat()
                new["checksum"] = syncmod.checksum_of(new)
                appmod.ingest_snapshot(old)
                appmod.ingest_snapshot(new)
                daily = appmod.leaderboard("daily")
                self.assertEqual(daily["users"][0]["tokens"], 2500)
                self.assertEqual(
                    {h["harness"]: h["tokens"] for h in daily["harnesses"]},
                    {"Codex": 2000, "Claude Code": 500})
                self.assertEqual(
                    {m["model"]: m["tokens"] for m in daily["models"]},
                    {"Codex/gpt-5": 2000, "Claude Code/opus": 500})
            finally:
                for p in patches:
                    p.stop()

    def test_weekly_fallback_without_baseline(self):
        """Both snapshots strictly inside the current week on ANY weekday, so
        no weekly baseline exists and the legacy fallback (full total) applies."""
        import datetime as _dt

        import server.app as appmod

        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            patches = self._patched_app(appmod, data)
            for p in patches:
                p.start()
            try:
                now = _dt.datetime.now(_dt.timezone.utc)
                monday = (now - _dt.timedelta(days=now.weekday())).replace(
                    hour=0, minute=0, second=0, microsecond=0)
                span = max((now - monday).total_seconds(), 120)
                old = syncmod.build_snapshot("b", "b@aganitha.ai", "other",
                                             [AgentReport(agent_name="Codex", models=[TokenStats(model_id="gpt-5", input_tokens=2000, session_count=1)])])
                old["collected_at"] = (monday + _dt.timedelta(seconds=span / 2)).isoformat()
                old["checksum"] = syncmod.checksum_of(old)
                new = syncmod.build_snapshot("b", "b@aganitha.ai", "other",
                                             [AgentReport(agent_name="Codex", models=[TokenStats(model_id="gpt-5", input_tokens=5000, session_count=1)])])
                new["collected_at"] = (now - _dt.timedelta(seconds=1)).isoformat()
                new["checksum"] = syncmod.checksum_of(new)
                appmod.ingest_snapshot(old)
                appmod.ingest_snapshot(new)
                weekly = appmod.leaderboard("weekly")
                self.assertEqual(weekly["users"][0]["tokens"], 5000)
                self.assertEqual(
                    {h["harness"]: h["tokens"] for h in weekly["harnesses"]},
                    {"Codex": 5000})
            finally:
                for p in patches:
                    p.stop()

    def test_multi_host_series_sum(self):
        """Two machines, same user: scores sum per host series, so a fresh
        laptop with lower counters can never zero the main machine's score."""
        import server.app as appmod

        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            with mock.patch.object(appmod, "DATA_DIR", data), \
                 mock.patch.object(appmod, "DB_PATH", data / "leaderboard.db"), \
                 mock.patch.object(appmod, "LEDGER_PATH", data / "ledger.jsonl"), \
                 mock.patch.object(appmod, "USERS_JSON", data / "users.json"):
                big = syncmod.build_snapshot("u", "u@aganitha.ai", "engineering", [_report("Codex", 100000)])
                big["host"] = "laptop-pro"
                big["checksum"] = syncmod.checksum_of(big)
                small = syncmod.build_snapshot("u", "u@aganitha.ai", "engineering", [_report("Codex", 100)])
                small["host"] = "fresh-laptop"
                small["checksum"] = syncmod.checksum_of(small)
                appmod.ingest_snapshot(big)
                appmod.ingest_snapshot(small)  # newer, lower — must not wipe score
                lb = appmod.leaderboard("daily")
                self.assertEqual(len(lb["users"]), 1)
                self.assertEqual(lb["users"][0]["tokens"], 100100)
                self.assertEqual(lb["users"][0]["pushes"], 2)

    def test_all_time_window(self):
        import datetime as _dt

        import server.app as appmod

        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            with mock.patch.object(appmod, "DATA_DIR", data), \
                 mock.patch.object(appmod, "DB_PATH", data / "leaderboard.db"), \
                 mock.patch.object(appmod, "LEDGER_PATH", data / "ledger.jsonl"), \
                 mock.patch.object(appmod, "USERS_JSON", data / "users.json"):
                now = _dt.datetime.now(_dt.timezone.utc)
                old = syncmod.build_snapshot("u", "u@aganitha.ai", "other", [_report("Codex", 1000)])
                old["collected_at"] = (now - _dt.timedelta(days=10)).isoformat()
                old["checksum"] = syncmod.checksum_of(old)
                new = syncmod.build_snapshot("u", "u@aganitha.ai", "other", [_report("Codex", 2500)])
                appmod.ingest_snapshot(old)
                appmod.ingest_snapshot(new)
                alltime = appmod.leaderboard("all")
                self.assertEqual(alltime["window"], "all")
                self.assertEqual(alltime["users"][0]["tokens"], 2500)
                self.assertEqual(alltime["users"][0]["cumulative"], 2500)
                self.assertEqual(appmod.leaderboard("bogus")["window"], "daily")

    def test_baseline_less_day_uses_today_portion(self):
        """Onboarding day (no pre-window baseline): lifetime history must not
        count as today's usage — the client-measured today portion does."""
        import server.app as appmod

        def _reps(codex_total):
            return [AgentReport(
                agent_name="Codex",
                models=[TokenStats(model_id="gpt-5", input_tokens=codex_total,
                                   session_count=1)])]

        def _today(codex_today):
            return [AgentReport(
                agent_name="Codex",
                models=[TokenStats(model_id="gpt-5", input_tokens=codex_today,
                                   session_count=1)])]

        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            with mock.patch.object(appmod, "DATA_DIR", data), \
                 mock.patch.object(appmod, "DB_PATH", data / "leaderboard.db"), \
                 mock.patch.object(appmod, "LEDGER_PATH", data / "ledger.jsonl"), \
                 mock.patch.object(appmod, "USERS_JSON", data / "users.json"):
                snap = syncmod.build_snapshot("u", "u@aganitha.ai", "other",
                                              _reps(100000), today_reports=_today(300))
                self.assertEqual(snap["today_total"], 300)
                self.assertIn("today_tokens", snap["models"][0])
                appmod.ingest_snapshot(snap)
                daily = appmod.leaderboard("daily")
                self.assertEqual(daily["users"][0]["tokens"], 300)
                self.assertEqual(daily["users"][0]["cumulative"], 100000)
                dh = {h["harness"]: h["tokens"] for h in daily["harnesses"]}
                self.assertEqual(dh, {"Codex": 300})
                # Without a today scan the legacy shape carries no today keys
                # and old snapshots keep the old fallback.
                legacy = syncmod.build_snapshot("v", "v@aganitha.ai", "other",
                                                _reps(50000))
                self.assertNotIn("today_tokens", legacy["models"][0])
                appmod.ingest_snapshot(legacy)
                self.assertEqual(
                    [u for u in appmod.leaderboard("daily")["users"]
                     if u["username"] == "v"][0]["tokens"], 50000)

    def test_doctor_checks(self):
        from agent_tokens import doctor as doctormod

        with mock.patch.object(doctormod, "_check_ssh", return_value=("ok", "ssh fine")):
            with mock.patch.object(doctormod, "_check_server", return_value=("warn", "gated")):
                with mock.patch("agent_tokens.identity.load_identity", return_value=None):
                    rc = doctormod.run_doctor()
        self.assertEqual(rc, 1)  # missing identity -> FAIL

    def test_ingest_rejects_xss_username(self):
        import server.app as appmod

        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            with mock.patch.object(appmod, "DATA_DIR", data), \
                 mock.patch.object(appmod, "DB_PATH", data / "leaderboard.db"), \
                 mock.patch.object(appmod, "LEDGER_PATH", data / "ledger.jsonl"), \
                 mock.patch.object(appmod, "USERS_JSON", data / "users.json"):
                evil = syncmod.build_snapshot(
                    '"><img src=x onerror=alert(1)>', "e@aganitha.ai", "other", [_report()])
                with self.assertRaises(ValueError):
                    appmod.ingest_snapshot(evil)
                evil_model = syncmod.build_snapshot("u", "u@aganitha.ai", "other", [_report()])
                evil_model["models"] = [{"agent_name": "Codex", "model_id": "<script>",
                                         "total_tokens": 5, "session_count": 0, "turn_count": 0}]
                evil_model["checksum"] = syncmod.checksum_of(evil_model)
                with self.assertRaises(ValueError):
                    appmod.ingest_snapshot(evil_model)
                # Real-world names (spaces, parens, slashes) still pass.
                ok = syncmod.build_snapshot("hriteek", "h@aganitha.ai", "engineering",
                                            [AgentReport(agent_name="Antigravity (AGY)",
                                                         models=[TokenStats(model_id="muse-spark-1.3",
                                                                            input_tokens=10)])])
                self.assertTrue(appmod.ingest_snapshot(ok)["ok"])

    def test_ingest_clamps_collected_at(self):
        import datetime as _dt

        import server.app as appmod

        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            with mock.patch.object(appmod, "DATA_DIR", data), \
                 mock.patch.object(appmod, "DB_PATH", data / "leaderboard.db"), \
                 mock.patch.object(appmod, "LEDGER_PATH", data / "ledger.jsonl"), \
                 mock.patch.object(appmod, "USERS_JSON", data / "users.json"):
                stale = syncmod.build_snapshot("u", "u@aganitha.ai", "other", [_report()])
                stale["collected_at"] = (
                    _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=60)).isoformat()
                stale["checksum"] = syncmod.checksum_of(stale)
                with self.assertRaises(ValueError):
                    appmod.ingest_snapshot(stale)
                future = syncmod.build_snapshot("u", "u@aganitha.ai", "other", [_report()])
                future["collected_at"] = (
                    _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(days=1)).isoformat()
                future["checksum"] = syncmod.checksum_of(future)
                with self.assertRaises(ValueError):
                    appmod.ingest_snapshot(future)

    def test_leaderboard_cache_invalidates_on_ingest(self):
        import server.app as appmod

        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            with mock.patch.object(appmod, "DATA_DIR", data), \
                 mock.patch.object(appmod, "DB_PATH", data / "leaderboard.db"), \
                 mock.patch.object(appmod, "LEDGER_PATH", data / "ledger.jsonl"), \
                 mock.patch.object(appmod, "USERS_JSON", data / "users.json"):
                appmod._board_cache_invalidate()
                appmod.ingest_snapshot(
                    syncmod.build_snapshot("u", "u@aganitha.ai", "other", [_report("Codex", 100)]))
                first = appmod.leaderboard("daily")
                self.assertEqual(first["users"][0]["tokens"], 100)
                cached = appmod.leaderboard("daily")
                self.assertIs(first, cached)  # TTL hit: same object
                appmod.ingest_snapshot(
                    syncmod.build_snapshot("u", "u@aganitha.ai", "other", [_report("Codex", 300)]))
                second = appmod.leaderboard("daily")
                self.assertIsNot(first, second)
                self.assertEqual(second["users"][0]["tokens"], 300)

    def test_ingest_token_gate(self):
        import server.app as appmod

        with mock.patch.object(appmod, "INGEST_TOKEN", ""):
            self.assertTrue(appmod._ingest_authorized({}, None))
        with mock.patch.object(appmod, "INGEST_TOKEN", "s3cret"):
            self.assertFalse(appmod._ingest_authorized({}, None))
            self.assertFalse(appmod._ingest_authorized({"token": ["wrong"]}, None))
            self.assertTrue(appmod._ingest_authorized({"token": ["s3cret"]}, None))

            class _H(dict):
                def get(self, k, d=""):
                    return super().get(k, d)

            self.assertTrue(appmod._ingest_authorized({}, _H({"X-Ingest-Token": "s3cret"})))
            self.assertFalse(appmod._ingest_authorized({}, _H({"X-Ingest-Token": "no"})))

    def test_replay_ledger_rebuilds_empty_db(self):
        import server.app as appmod

        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            with mock.patch.object(appmod, "DATA_DIR", data), \
                 mock.patch.object(appmod, "DB_PATH", data / "leaderboard.db"), \
                 mock.patch.object(appmod, "LEDGER_PATH", data / "ledger.jsonl"), \
                 mock.patch.object(appmod, "USERS_JSON", data / "users.json"):
                appmod.ingest_snapshot(
                    syncmod.build_snapshot("u", "u@aganitha.ai", "other", [_report("Codex", 500)]))
                self.assertEqual(len(appmod.leaderboard("daily")["users"]), 1)
                # Lose the DB (fresh volume): replay restores from the ledger.
                (data / "leaderboard.db").unlink()
                appmod._board_cache_invalidate()
                self.assertEqual(appmod.replay_ledger(), 1)
                self.assertEqual(appmod.leaderboard("daily")["users"][0]["tokens"], 500)
                # No-op when the DB is already populated.
                self.assertEqual(appmod.replay_ledger(), 0)


if __name__ == "__main__":
    unittest.main()
