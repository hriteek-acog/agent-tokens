"""Unit tests for agent-tokens formatters."""

import unittest
from agent_tokens.formatters import format_number, render_terminal, render_json
from agent_tokens.models import AgentReport, TokenStats


class TestFormatters(unittest.TestCase):
    def test_format_number(self):
        self.assertEqual(format_number(500), "500")
        self.assertEqual(format_number(1500), "1.5K")
        self.assertEqual(format_number(2_500_000), "2.50M")
        self.assertEqual(format_number(1_200_000_000), "1.20B")

    def test_render_json(self):
        m = TokenStats(model_id="gpt-4o", input_tokens=100, output_tokens=50)
        rep = AgentReport(agent_name="Test", models=[m])
        output = render_json([rep])
        self.assertIn("gpt-4o", output)
        self.assertIn("150", output)


if __name__ == "__main__":
    unittest.main()
