"""Main CLI entrypoint for agent-tokens command."""

import argparse
import sys
from typing import List

from agent_tokens.providers.base import BaseProvider
from agent_tokens.providers.opencode import OpenCodeProvider
from agent_tokens.providers.claude import ClaudeCodeProvider
from agent_tokens.providers.antigravity import AntigravityProvider
from agent_tokens.formatters import render_terminal, render_json


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="agent-tokens",
        description="Unified token and session analytics across OpenCode, Claude Code, and Antigravity (AGY).",
    )
    parser.add_argument(
        "--today", action="store_true", help="Filter metrics to today's active sessions only"
    )
    parser.add_argument(
        "--opencode", action="store_true", help="Display only OpenCode usage"
    )
    parser.add_argument(
        "--claude", action="store_true", help="Display only Claude Code usage"
    )
    parser.add_argument(
        "--agy", action="store_true", help="Display only Google Antigravity (AGY) usage"
    )
    parser.add_argument(
        "--json", action="store_true", help="Output machine-readable JSON format"
    )

    args = parser.parse_args()

    providers: List[BaseProvider] = []
    # If specific flags are chosen, only run those
    filter_set = args.opencode or args.claude or args.agy

    if not filter_set or args.opencode:
        providers.append(OpenCodeProvider())
    if not filter_set or args.claude:
        providers.append(ClaudeCodeProvider())
    if not filter_set or args.agy:
        providers.append(AntigravityProvider())

    reports = []
    for provider in providers:
        if provider.is_available():
            rep = provider.get_report(today_only=args.today)
            if rep:
                reports.append(rep)

    if args.json:
        print(render_json(reports))
    else:
        time_scope = "TODAY" if args.today else "ALL-TIME"
        print(render_terminal(reports, time_scope=time_scope))


if __name__ == "__main__":
    main()
