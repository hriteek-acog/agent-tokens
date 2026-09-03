"""Unit tests for agent-tokens models."""

import unittest
from agent_tokens.models import TokenStats, SessionInfo, AgentReport


class TestModels(unittest.TestCase):
    def test_token_stats_total_includes_all_categories(self):
        stats = TokenStats(
            model_id="test-model",
            input_tokens=1000,
            output_tokens=200,
            reasoning_tokens=50,
            cache_read_tokens=5000,
            cache_write_tokens=500,
        )
        # 1000 + 200 + 50 + 5000 + 500
        self.assertEqual(stats.total_tokens, 6750)
        d = stats.to_dict()
        self.assertEqual(d["total_tokens"], 6750)
        self.assertEqual(d["model_id"], "test-model")

    def test_token_stats_coerces_none_and_float(self):
        stats = TokenStats(
            model_id="m",
            input_tokens=None,
            output_tokens=10.9,
            cache_read_tokens=None,
        )
        self.assertEqual(stats.input_tokens, 0)
        self.assertEqual(stats.output_tokens, 10)
        self.assertEqual(stats.cache_read_tokens, 0)
        self.assertEqual(stats.total_tokens, 10)

    def test_session_info_total_includes_reasoning_and_cache_write(self):
        s = SessionInfo(
            session_id="s-123",
            title="Test Session",
            model_id="test-model",
            input_tokens=500,
            output_tokens=100,
            reasoning_tokens=50,
            cache_read_tokens=2000,
            cache_write_tokens=100,
        )
        self.assertEqual(s.total_tokens, 2750)
        d = s.to_dict()
        self.assertEqual(d["total_tokens"], 2750)
        self.assertEqual(d["cache_write_tokens"], 100)

    def test_session_info_defaults_title_and_model(self):
        s = SessionInfo(session_id="abcdef1234567890xyz", title="", model_id="")
        self.assertTrue(s.title)
        self.assertEqual(s.model_id, "unknown")

    def test_agent_report_total(self):
        m1 = TokenStats(model_id="m1", input_tokens=100, output_tokens=50)
        m2 = TokenStats(model_id="m2", input_tokens=200, output_tokens=100)
        report = AgentReport(agent_name="TestAgent", models=[m1, m2])
        self.assertEqual(report.total_tokens, 450)

    def test_agent_report_empty(self):
        report = AgentReport(agent_name="Empty")
        self.assertEqual(report.total_tokens, 0)
        d = report.to_dict()
        self.assertEqual(d["models"], [])
        self.assertEqual(d["recent_sessions"], [])


if __name__ == "__main__":
    unittest.main()
