"""Unit tests for agent-tokens models."""

import unittest
from agent_tokens.models import TokenStats, SessionInfo, AgentReport


class TestModels(unittest.TestCase):
    def test_token_stats_total(self):
        stats = TokenStats(
            model_id="test-model",
            input_tokens=1000,
            output_tokens=200,
            reasoning_tokens=50,
            cache_read_tokens=5000,
            cache_write_tokens=500,
        )
        self.assertEqual(stats.total_tokens, 6700)
        d = stats.to_dict()
        self.assertEqual(d["total_tokens"], 6700)
        self.assertEqual(d["model_id"], "test-model")

    def test_session_info_total(self):
        s = SessionInfo(
            session_id="s-123",
            title="Test Session",
            model_id="test-model",
            input_tokens=500,
            output_tokens=100,
            cache_read_tokens=2000,
        )
        self.assertEqual(s.total_tokens, 2600)

    def test_agent_report_total(self):
        m1 = TokenStats(model_id="m1", input_tokens=100, output_tokens=50)
        m2 = TokenStats(model_id="m2", input_tokens=200, output_tokens=100)
        report = AgentReport(agent_name="TestAgent", models=[m1, m2])
        self.assertEqual(report.total_tokens, 450)


if __name__ == "__main__":
    unittest.main()
