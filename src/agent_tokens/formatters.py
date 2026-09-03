"""Terminal ANSI and JSON formatters for agent reports."""

import json
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


def format_number(n: int) -> str:
    """Convert large integer counts into compact human-readable strings (e.g. 1.25M, 450K)."""
    if n is None:
        return "0"
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.2f}B"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return f"{n:,}"


def render_terminal(reports: List[AgentReport], time_scope: str = "ALL-TIME") -> str:
    """Format and render a clean, modern ANSI terminal dashboard."""
    lines = []
    lines.append(f"\n{BOLD}{CYAN}════════════════════════════════════════════════════════════════════════════════{RESET}")
    lines.append(f"{BOLD}{CYAN}                    🤖 MULTI-AGENT TOKEN TRACKER ({time_scope}){RESET}")
    lines.append(f"{BOLD}{CYAN}════════════════════════════════════════════════════════════════════════════════{RESET}\n")

    grand_total_tokens = 0

    color_map = {
        "OpenCode": GREEN,
        "Claude Code": YELLOW,
        "Antigravity (AGY)": BLUE,
    }

    for report in reports:
        if not report:
            continue
        color = color_map.get(report.agent_name, MAGENTA)
        lines.append(f"{BOLD}{color}► {report.agent_name.upper()}{RESET}")
        lines.append(f"{DIM}────────────────────────────────────────────────────────────────────────────────{RESET}")

        if not report.models:
            lines.append(f"  {DIM}No activity recorded for this timeframe.{RESET}\n")
            continue

        lines.append(
            f"{BOLD}{'Model':<34} {'Sessions':<9} {'Input':<10} {'Output':<10} {'Reasoning':<10} {'Cache/Read':<11} {'Total':<10}{RESET}"
        )
        lines.append(f"{DIM}{'-'*96}{RESET}")

        for m in report.models:
            grand_total_tokens += m.total_tokens
            lines.append(
                f"{m.model_id:<34} {m.session_count:<9} {format_number(m.input_tokens):<10} "
                f"{format_number(m.output_tokens):<10} {format_number(m.reasoning_tokens):<10} "
                f"{format_number(m.cache_read_tokens):<11} {BOLD}{format_number(m.total_tokens):<10}{RESET}"
            )

        if report.recent_sessions:
            lines.append(f"\n  {BOLD}Recent Active Sessions:{RESET}")
            for s in report.recent_sessions[:5]:
                t = s.title if len(s.title) <= 45 else s.title[:42] + "..."
                lines.append(f"  • {BOLD}{t:<45}{RESET} ({s.model_id})")
                lines.append(
                    f"    Total: {format_number(s.total_tokens)} "
                    f"(In: {format_number(s.input_tokens)}, Out: {format_number(s.output_tokens)}, "
                    f"Reasoning: {format_number(s.reasoning_tokens)}, Cache: {format_number(s.cache_read_tokens)}) "
                    f"{DIM}{s.updated_at or ''}{RESET}"
                )

        lines.append("")

    lines.append(f"{BOLD}{MAGENTA}════════════════════════════════════════════════════════════════════════════════{RESET}")
    lines.append(
        f"{BOLD}🎯 GRAND TOTAL TOKENS PROCESSED ({time_scope}): {GREEN}{format_number(grand_total_tokens)}{RESET} "
        f"{DIM}({grand_total_tokens:,} tokens){RESET}"
    )
    lines.append(f"{BOLD}{MAGENTA}════════════════════════════════════════════════════════════════════════════════{RESET}\n")

    return "\n".join(lines)


def render_json(reports: List[AgentReport]) -> str:
    """Export reports as formatted JSON."""
    data = [r.to_dict() for r in reports if r]
    return json.dumps(data, indent=2)
