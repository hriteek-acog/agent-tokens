"""Main CLI entrypoint for agent-tokens command."""

import argparse
import os
import sys
from typing import List

from agent_tokens import __version__
from agent_tokens.providers.base import BaseProvider
from agent_tokens.providers.opencode import OpenCodeProvider
from agent_tokens.providers.claude import ClaudeCodeProvider
from agent_tokens.providers.antigravity import AntigravityProvider
from agent_tokens.formatters import render_terminal, render_json


def build_parser() -> argparse.ArgumentParser:
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
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI colors (also honours the NO_COLOR env var)",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    return parser


def collect_reports(providers: List[BaseProvider], today_only: bool):
    """Query each provider in isolation so one corrupt store can't sink the run."""
    reports = []
    for provider in providers:
        try:
            if not provider.is_available():
                continue
        except Exception as exc:  # defensive: exotic filesystems/permissions
            print(f"warning: {provider.name} availability check failed: {exc}", file=sys.stderr)
            continue
        try:
            rep = provider.get_report(today_only=today_only)
        except Exception as exc:
            print(f"warning: {provider.name} report failed ({exc}); skipping.", file=sys.stderr)
            continue
        if rep:
            reports.append(rep)
    return reports


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    providers: List[BaseProvider] = []
    # If specific flags are chosen, only run those
    filter_set = args.opencode or args.claude or args.agy

    if not filter_set or args.opencode:
        providers.append(OpenCodeProvider())
    if not filter_set or args.claude:
        providers.append(ClaudeCodeProvider())
    if not filter_set or args.agy:
        providers.append(AntigravityProvider())

    reports = collect_reports(providers, today_only=args.today)

    use_color = not args.no_color and os.environ.get("NO_COLOR") is None

    if args.json:
        print(render_json(reports))
    else:
        time_scope = "TODAY" if args.today else "ALL-TIME"
        print(render_terminal(reports, time_scope=time_scope, use_color=use_color))
        if not reports or not any(r.models for r in reports):
            print(
                "No agent data matched. Providers checked: "
                + ", ".join(p.name for p in providers),
                file=sys.stderr,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
