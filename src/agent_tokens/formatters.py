"""Terminal ANSI and JSON formatters for agent reports."""

import json
import os
from typing import List
from agent_tokens.models import AgentReport

# Color palette
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
MAGENTA = "\033[95m"
BLUE = "\033[94m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


def _colors_enabled(use_color: bool) -> bool:
    if not use_color:
        return False
    if os.environ.get("NO_COLOR"):
        return False
    return True


def _paint(text: str, code: str, enabled: bool) -> str:
    return f"{code}{text}{RESET}" if enabled else text


def format_number(n: object) -> str:
    """Convert large integer counts into compact human-readable strings (e.g. 1.25M, 450K)."""
    if isinstance(n, bool):
        return "0"
    if n is None:
        return "0"
    if isinstance(n, float):
        n = int(n)
    if not isinstance(n, int):
        try:
            n = int(n)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return "0"
    if n < 0:
        n = 0
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.2f}B"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return f"{n:,}"


def _cache_total(m) -> int:
    return (m.cache_read_tokens or 0) + (m.cache_write_tokens or 0)


def render_terminal(
    reports: List[AgentReport],
    time_scope: str = "ALL-TIME",
    use_color: bool = True,
) -> str:
    """Format and render a clean, modern ANSI terminal dashboard.

    ``use_color`` is honoured together with the ``NO_COLOR`` environment
    convention so piped output stays clean.
    """
    color = _colors_enabled(use_color)
    B = BOLD if color else ""
    R = RESET if color else ""
    C = CYAN if color else ""
    G = GREEN if color else ""
    Y = YELLOW if color else ""
    M = MAGENTA if color else ""
    BL = BLUE if color else ""
    D = DIM if color else ""

    lines = []
    lines.append(f"\n{B}{C}════════════════════════════════════════════════════════════════════════════════{R}")
    lines.append(f"{B}{C}                    🤖 MULTI-AGENT TOKEN TRACKER ({time_scope}){R}")
    lines.append(f"{B}{C}════════════════════════════════════════════════════════════════════════════════{R}\n")

    grand_total_tokens = 0
    visible_reports = [r for r in reports if r is not None]

    color_map = {
        "OpenCode": G,
        "Claude Code": Y,
        "Antigravity (AGY)": BL,
        "Codex": G,
        "Copilot": C,
        "Cursor": BL,
        "Gemini CLI": C,
        "Qwen Code": Y,
        "Pi": G,
        "DeepSeek": M,
        "Cline": Y,
        "Windsurf": BL,
    }

    if not visible_reports or not any(r.models for r in visible_reports):
        lines.append(f"  {D}No token activity found for this timeframe.{R}")
        lines.append(f"  {D}Tip: run without --today, or check that agent data stores exist.{R}\n")

    for report in visible_reports:
        accent = color_map.get(report.agent_name, M)
        lines.append(f"{B}{accent}► {report.agent_name.upper()}{R}")
        lines.append(f"{D}────────────────────────────────────────────────────────────────────────────────{R}")

        if not report.models:
            lines.append(f"  {D}No activity recorded for this timeframe.{R}\n")
            continue

        show_turns = any((m.turn_count or 0) > 0 for m in report.models)
        if show_turns:
            lines.append(
                f"{B}{'Model':<30} {'Sessions':<8} {'Turns':<6} {'Input':<9} {'Output':<9} {'Reason':<8} {'Cache':<10} {'Total':<10}{R}"
            )
        else:
            lines.append(
                f"{B}{'Model':<34} {'Sessions':<9} {'Input':<10} {'Output':<10} {'Reasoning':<10} {'Cache':<11} {'Total':<10}{R}"
            )
        lines.append(f"{D}{'-'*96}{R}")

        for m in report.models:
            grand_total_tokens += m.total_tokens
            cache = _cache_total(m)
            if show_turns:
                lines.append(
                    f"{m.model_id:<30} {m.session_count:<8} {m.turn_count:<6} "
                    f"{format_number(m.input_tokens):<9} "
                    f"{format_number(m.output_tokens):<9} {format_number(m.reasoning_tokens):<8} "
                    f"{format_number(cache):<10} {B}{format_number(m.total_tokens):<10}{R}"
                )
            else:
                lines.append(
                    f"{m.model_id:<34} {m.session_count:<9} {format_number(m.input_tokens):<10} "
                    f"{format_number(m.output_tokens):<10} {format_number(m.reasoning_tokens):<10} "
                    f"{format_number(cache):<11} {B}{format_number(m.total_tokens):<10}{R}"
                )

        if report.recent_sessions:
            lines.append(f"\n  {B}Recent Active Sessions:{R}")
            for s in report.recent_sessions[:5]:
                title = s.title or s.session_id[:18]
                t = title if len(title) <= 45 else title[:42] + "..."
                turns_suffix = f" · {s.turn_count} turns" if (s.turn_count or 0) > 0 else ""
                lines.append(f"  • {B}{t:<45}{R} ({s.model_id})")
                lines.append(
                    f"    Total: {format_number(s.total_tokens)} "
                    f"(In: {format_number(s.input_tokens)}, Out: {format_number(s.output_tokens)}, "
                    f"Reasoning: {format_number(s.reasoning_tokens)}, Cache: {format_number((s.cache_read_tokens or 0) + (s.cache_write_tokens or 0))}){turns_suffix} "
                    f"{D}{s.updated_at or ''}{R}"
                )

        lines.append("")

    lines.append(f"{B}{M}════════════════════════════════════════════════════════════════════════════════{R}")
    lines.append(
        f"{B}🎯 GRAND TOTAL TOKENS PROCESSED ({time_scope}): {G}{format_number(grand_total_tokens)}{R} "
        f"{D}({grand_total_tokens:,} tokens){R}"
    )
    lines.append(f"{B}{M}════════════════════════════════════════════════════════════════════════════════{R}\n")

    return "\n".join(lines)


def render_json(reports: List[AgentReport]) -> str:
    """Export reports as formatted JSON."""
    data = [r.to_dict() for r in reports if r]
    return json.dumps(data, indent=2)
