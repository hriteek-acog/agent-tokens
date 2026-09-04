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
    def _fresh_server(self, td):
        import server.app as appmod

        data = Path(td)
        with mock.patch.object(appmod, "DATA_DIR", data), \
             mock.patch.object(appmod, "DB_PATH", data / "leaderboard.db"), \
             mock.patch.object(appmod, "LEDGER_PATH", data / "ledger.jsonl"), \
             mock.patch.object(appmod, "USERS_JSON", data / "users.json"):
            yield appmod

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


if __name__ == "__main__":
    unittest.main()
