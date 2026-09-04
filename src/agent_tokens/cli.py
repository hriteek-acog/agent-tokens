"""Main CLI entrypoint for agent-tokens command."""

import argparse
import os
import sys
from typing import List

from agent_tokens import __version__
from agent_tokens.providers import ALL_PROVIDERS, FLAG_MAP
from agent_tokens.providers.base import BaseProvider
from agent_tokens.formatters import render_terminal, render_json

FILTER_FLAGS = (
    ("opencode", "Display only OpenCode usage"),
    ("claude", "Display only Claude Code usage"),
    ("agy", "Display only Google Antigravity (AGY) usage"),
    ("codex", "Display only OpenAI Codex usage"),
    ("copilot", "Display only GitHub Copilot usage"),
    ("cursor", "Display only Cursor usage"),
    ("gemini", "Display only Gemini CLI usage"),
    ("qwen", "Display only Qwen Code usage"),
    ("pi", "Display only Pi agent usage"),
    ("deepseek", "Display only DeepSeek harness usage"),
    ("cline", "Display only Cline usage"),
    ("windsurf", "Display only Windsurf usage"),
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-tokens",
        description=(
            "Unified token and session analytics across 12 coding agents: "
            "OpenCode, Claude Code, Antigravity (AGY), Codex, Copilot, Cursor, "
            "Gemini CLI, Qwen Code, Pi, DeepSeek, Cline, and Windsurf."
        ),
    )
    parser.add_argument(
        "--today", action="store_true", help="Filter metrics to today's active sessions only"
    )
    for flag, help_text in FILTER_FLAGS:
        parser.add_argument(f"--{flag}", action="store_true", help=help_text)
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

    # If specific agent flags are chosen, only run those; otherwise all 12.
    selected = [flag for flag, _ in FILTER_FLAGS if getattr(args, flag)]
    if selected:
        providers = [FLAG_MAP[flag]() for flag in selected]
    else:
        providers = [cls() for cls in ALL_PROVIDERS]

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
