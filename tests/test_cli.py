"""Unit tests for agent-tokens CLI dispatch (12-agent registry)."""

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from agent_tokens import __version__
from agent_tokens.cli import build_parser, collect_reports, main
from agent_tokens.models import AgentReport, TokenStats
from agent_tokens.providers import ALL_PROVIDERS, FLAG_MAP


def _report(name="OpenCode"):
    return AgentReport(
        agent_name=name, models=[TokenStats(model_id="m1", input_tokens=100)]
    )


class _FailingProvider:
    name = "Broken"

    def is_available(self):
        return True

    def get_report(self, today_only=False):
        raise RuntimeError("boom")


class _Provider:
    def __init__(self, name, report):
        self.name = name
        self._report = report

    def is_available(self):
        return True

    def get_report(self, today_only=False):
        return self._report


def _stub_provider_class(report):
    """Build a provider class returning a canned report (for registry patching)."""

    class _Stub:
        def __init__(self, *a, **k):
            pass

        @property
        def name(self):
            return report.agent_name if report else "Stub"

        def is_available(self):
            return True

        def get_report(self, today_only=False):
            return report

    return _Stub


class _RegistryPatch:
    """Context manager swapping cli.ALL_PROVIDERS for canned stub classes."""

    def __init__(self, reports):
        self.reports = reports
        self._patcher = None

    def __enter__(self):
        stubs = tuple(_stub_provider_class(r) for r in self.reports)
        self._patcher = mock.patch("agent_tokens.cli.ALL_PROVIDERS", stubs)
        self._patcher.start()
        return self

    def __exit__(self, *exc):
        self._patcher.stop()
        return False


class TestCLI(unittest.TestCase):
    def test_registry_covers_twelve_agents(self):
        self.assertEqual(len(ALL_PROVIDERS), 12)
        self.assertEqual(len(FLAG_MAP), 12)
        for flag in ("opencode", "claude", "agy", "codex", "copilot", "cursor",
                     "gemini", "qwen", "pi", "deepseek", "cline", "windsurf"):
            self.assertIn(flag, FLAG_MAP)

    def test_version_flag(self):
        with self.assertRaises(SystemExit) as ctx:
            build_parser().parse_args(["--version"])
        self.assertEqual(ctx.exception.code, 0)
        self.assertTrue(__version__)

    def test_agent_filter_flags_accepted(self):
        args = build_parser().parse_args(["--codex", "--today"])
        self.assertTrue(args.codex)
        self.assertTrue(args.today)
        self.assertFalse(args.cursor)

    def test_collect_reports_isolates_failures(self):
        err = io.StringIO()
        with redirect_stderr(err):
            reports = collect_reports([_FailingProvider(), _Provider("Ok", _report())], False)
        self.assertEqual(len(reports), 1)
        self.assertIn("Broken", err.getvalue())

    def test_main_agent_filter_selects_subset(self):
        seen = []

        class _Spy(_Provider):
            def get_report(self, today_only=False):
                seen.append(self.name)
                return None

        with mock.patch.dict(
            "agent_tokens.cli.FLAG_MAP",
            {"codex": lambda: _Spy("Codex", None), "pi": lambda: _Spy("Pi", None)},
        ):
            out = io.StringIO()
            with redirect_stdout(out):
                rc = main(["--codex", "--json"])
        self.assertEqual(rc, 0)
        self.assertEqual(seen, ["Codex"])

    def test_main_json_output(self):
        with _RegistryPatch([_report("OpenCode"), None, None]):
            out = io.StringIO()
            with redirect_stdout(out):
                rc = main(["--json"])
        self.assertEqual(rc, 0)
        parsed = json.loads(out.getvalue())
        self.assertEqual(parsed[0]["agent_name"], "OpenCode")

    def test_main_empty_reports_warns_on_stderr(self):
        with _RegistryPatch([AgentReport(agent_name="OpenCode"), None]):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                rc = main([])
        self.assertEqual(rc, 0)
        self.assertIn("No token activity", out.getvalue())
        self.assertIn("No agent data matched", err.getvalue())


if __name__ == "__main__":
    unittest.main()
