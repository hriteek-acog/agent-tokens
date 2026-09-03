"""Unit tests for agent-tokens formatters."""

import json
import unittest
from agent_tokens.formatters import format_number, render_terminal, render_json
from agent_tokens.models import AgentReport, TokenStats, SessionInfo


class TestFormatters(unittest.TestCase):
    def test_format_number(self):
        self.assertEqual(format_number(500), "500")
        self.assertEqual(format_number(1500), "1.5K")
        self.assertEqual(format_number(2_500_000), "2.50M")
        self.assertEqual(format_number(1_200_000_000), "1.20B")

    def test_format_number_edge_cases(self):
        self.assertEqual(format_number(None), "0")
        self.assertEqual(format_number(0), "0")
        self.assertEqual(format_number(-5), "0")
        self.assertEqual(format_number(999), "999")
        self.assertEqual(format_number(1000), "1.0K")
        self.assertEqual(format_number(True), "0")  # bool is not a token count

    def test_render_json(self):
        m = TokenStats(model_id="gpt-4o", input_tokens=100, output_tokens=50)
        rep = AgentReport(agent_name="Test", models=[m])
        output = render_json([rep])
        self.assertIn("gpt-4o", output)
        self.assertIn("150", output)
        parsed = json.loads(output)
        self.assertEqual(parsed[0]["total_tokens"], 150)

    def test_render_terminal_empty(self):
        out = render_terminal([], time_scope="TODAY", use_color=False)
        self.assertIn("No token activity found", out)
        self.assertIn("TODAY", out)

    def test_render_terminal_no_color(self):
        m = TokenStats(model_id="m1", input_tokens=100, output_tokens=50)
        rep = AgentReport(agent_name="OpenCode", models=[m])
        out = render_terminal([rep], use_color=False)
        self.assertNotIn("\033[", out)
        self.assertIn("m1", out)

    def test_render_terminal_combines_cache_read_and_write(self):
        m = TokenStats(
            model_id="m1", input_tokens=100, output_tokens=50,
            cache_read_tokens=1000, cache_write_tokens=500,
        )
        rep = AgentReport(agent_name="OpenCode", models=[m])
        out = render_terminal([rep], use_color=False)
        # total = 100 + 50 + 1500 = 1650 -> "1.6K"; cache col = 1500 -> "1.5K"
        self.assertIn("1.6K", out)
        self.assertIn("1.5K", out)

    def test_render_terminal_shows_turns_when_present(self):
        m = TokenStats(model_id="m1", input_tokens=10, turn_count=7, session_count=1)
        rep = AgentReport(agent_name="Antigravity (AGY)", models=[m])
        out = render_terminal([rep], use_color=False)
        self.assertIn("Turns", out)

    def test_render_terminal_hides_turns_when_absent(self):
        m = TokenStats(model_id="m1", input_tokens=10, session_count=1)
        rep = AgentReport(agent_name="OpenCode", models=[m])
        out = render_terminal([rep], use_color=False)
        self.assertNotIn("Turns", out)

    def test_render_terminal_session_turn_suffix(self):
        m = TokenStats(model_id="m1", input_tokens=10)
        s = SessionInfo(
            session_id="s1", title="Hello", model_id="m1",
            input_tokens=10, turn_count=3,
        )
        rep = AgentReport(agent_name="OpenCode", models=[m], recent_sessions=[s])
        out = render_terminal([rep], use_color=False)
        self.assertIn("3 turns", out)


if __name__ == "__main__":
    unittest.main()
