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
    # --- org leaderboard ---
    parser.add_argument(
        "--onboard",
        action="store_true",
        help="First-run setup: link this machine to your org identity",
    )
    parser.add_argument("--email", default=None, help="Org email for --onboard")
    parser.add_argument("--role", default=None, help="Role for --onboard")
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Push a full snapshot to the org leaderboard server now",
    )
    parser.add_argument(
        "--me", action="store_true", help="Show linked org identity and exit"
    )
    parser.add_argument(
        "--doctor",
        action="store_true",
        help="Preflight: check install, identity, server, and ssh-drop sync",
    )
    parser.add_argument(
        "--no-sync",
        action="store_true",
        help="Skip the background leaderboard push for this run",
    )
    parser.add_argument(
        "--server",
        default=None,
        help="Leaderboard server base URL (default: $AGENT_TOKENS_SERVER)",
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

    # --- org identity commands (no provider scan needed) ---
    if args.doctor:
        from agent_tokens.doctor import run_doctor

        return run_doctor(server_url=args.server)

    if args.me:
        from agent_tokens.identity import load_identity

        ident = load_identity()
        if not ident:
            print("No org identity linked. Run: agent-tokens --onboard --email you@aganitha.ai --role engineering")
            return 1
        print(f"{ident.username} <{ident.email}> [{ident.role}] verified={ident.verified}")
        return 0

    if args.onboard:
        from agent_tokens.identity import onboard as do_onboard

        if not args.email or not args.role:
            print("Usage: agent-tokens --onboard --email you@aganitha.ai --role engineering", file=sys.stderr)
            return 2
        try:
            ident = do_onboard(args.email, args.role)
        except ValueError as exc:
            print(f"onboard failed: {exc}", file=sys.stderr)
            return 2
        print(f"Linked {ident.username} <{ident.email}> [{ident.role}]")
        print("Dashboard identity ready. Your usage will now sync on every run.")
        return 0

    # If specific agent flags are chosen, only DISPLAY those; a full background
    # scan still runs for the org snapshot (see _maybe_sync below).
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

    # --- org sync: every normal run pushes a FULL all-agent snapshot ---
    sync_requested = args.sync or not args.no_sync
    if sync_requested:
        _maybe_sync(selected_filter=selected, server_url=args.server)
    return 0


def _maybe_sync(selected_filter, server_url=None) -> None:
    """Best-effort background push. Never breaks the local display path."""
    if os.environ.get("AGENT_TOKENS_NO_SYNC") == "1":
        return  # hard kill-switch: tests and scripts set this, checked first
    try:
        from agent_tokens import identity as _ident
        from agent_tokens import sync as _sync

        ident = _ident.load_identity()
        if not ident:
            return  # not onboarded yet — stay silent, stay local
        # Full scan regardless of display filter: leaderboard sees everything.
        full_providers = [cls() for cls in ALL_PROVIDERS]
        full_reports = collect_reports(full_providers, today_only=False)
        payload = _sync.build_snapshot(
            ident.username, ident.email, ident.role, full_reports,
            client_version=__version__,
        )
        server = server_url or _sync.DEFAULT_SERVER_URL
        result = _sync.sync_snapshot(payload, server_url=server)
        print(f"[leaderboard] synced via {result['transport']}", file=sys.stderr)
    except Exception as exc:  # sync must never fail the CLI
        print(f"[leaderboard] sync skipped ({exc})", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
