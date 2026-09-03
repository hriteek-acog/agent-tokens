"""Unit tests for agent-tokens CLI dispatch."""

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from agent_tokens import __version__
from agent_tokens.cli import build_parser, collect_reports, main
from agent_tokens.models import AgentReport, TokenStats


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


class TestCLI(unittest.TestCase):
    def test_version_flag(self):
        with self.assertRaises(SystemExit) as ctx:
            build_parser().parse_args(["--version"])
        self.assertEqual(ctx.exception.code, 0)
        self.assertTrue(__version__)

    def test_collect_reports_isolates_failures(self):
        err = io.StringIO()
        with redirect_stderr(err):
            reports = collect_reports([_FailingProvider(), _Provider("Ok", _report())], False)
        self.assertEqual(len(reports), 1)
        self.assertIn("Broken", err.getvalue())

    def test_main_json_output(self):
        with mock.patch(
            "agent_tokens.cli.OpenCodeProvider",
            return_value=_Provider("OpenCode", _report("OpenCode")),
        ), mock.patch(
            "agent_tokens.cli.ClaudeCodeProvider",
            return_value=_Provider("Claude Code", None),
        ), mock.patch(
            "agent_tokens.cli.AntigravityProvider",
            return_value=_Provider("AGY", None),
        ):
            out = io.StringIO()
            with redirect_stdout(out):
                rc = main(["--json"])
        self.assertEqual(rc, 0)
        parsed = json.loads(out.getvalue())
        self.assertEqual(parsed[0]["agent_name"], "OpenCode")

    def test_main_empty_reports_warns_on_stderr(self):
        with mock.patch(
            "agent_tokens.cli.OpenCodeProvider",
            return_value=_Provider("OpenCode", AgentReport(agent_name="OpenCode")),
        ), mock.patch(
            "agent_tokens.cli.ClaudeCodeProvider",
            return_value=_Provider("Claude Code", None),
        ), mock.patch(
            "agent_tokens.cli.AntigravityProvider",
            return_value=_Provider("AGY", None),
        ):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                rc = main([])
        self.assertEqual(rc, 0)
        self.assertIn("No token activity", out.getvalue())
        self.assertIn("No agent data matched", err.getvalue())


if __name__ == "__main__":
    unittest.main()
