# agent-tokens

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python Version](https://img.shields.io/badge/python-3.9+-brightgreen.svg)](pyproject.toml)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux-lightgrey.svg)](#)

Local-first CLI that aggregates token usage and session activity across 12 AI coding agents into one terminal dashboard and JSON pipeline. No API keys, no network calls.

Supported agents: OpenCode, Claude Code, Antigravity (AGY), Codex, Copilot, Cursor, Gemini CLI, Qwen Code, Pi, DeepSeek, Cline, Windsurf.

## Install

Requires Python 3.9+ on macOS or Linux.

```bash
git clone https://github.com/hritxx/agent-tokens.git
cd agent-tokens
pip install -e .
agent-tokens --version
```

## Usage

```bash
agent-tokens                  # all agents, all time
agent-tokens --today          # today's activity only
agent-tokens --codex          # one agent (also: --opencode --claude --agy
                              #   --copilot --cursor --gemini --qwen --pi
                              #   --deepseek --cline --windsurf)
agent-tokens --today --json   # machine-readable output for scripts/dashboards
agent-tokens --no-color        # plain output (also respects NO_COLOR=1)
```

Exit code is 0 on success. Providers are queried independently: an unreadable store prints a `warning:` to stderr and the rest still render.

## How it works

Each agent keeps usage in a different local format (SQLite, JSON caches, JSONL rollouts, protobuf blobs). One `BaseProvider` implementation per agent normalises these into `AgentReport` (per-model `TokenStats` plus `recent_sessions`), rendered as a terminal table or JSON.

- Databases are opened read-only; running agents are never locked.
- Totals are defined as `input + output + reasoning + cache_read + cache_write`. The `Cache` column shows reads + writes combined, so rows add up.
- The `Turns` column appears per agent only when turn data exists.

## Supported agents

| Agent | Local source | Fidelity |
|---|---|---|
| OpenCode | `~/.local/share/opencode/opencode.db` (`session` table) | Exact tokens, sessions |
| Claude Code | `~/.claude/stats-cache.json` | Exact all-time; today split estimated from all-time ratios (v5 schema stores day totals only); no per-session data upstream |
| Antigravity | `~/.gemini/antigravity-cli/conversations/*.db` | Exact tokens (protobuf), sessions |
| Codex | `~/.codex/sessions/**/rollout-*.jsonl` | Exact tokens; pre-split rollouts attributed to input as `codex-unknown` |
| Copilot | `~/.copilot/session-state/*/events.jsonl` + VSCode `github.copilot-chat/session-store.db` | Sessions/turns exact; tokens estimated from harness context size |
| Cursor | Cursor `workspaceStorage` directories | Sessions/recency only (no local token counters) |
| Gemini CLI | `~/.gemini/tmp/**/*.json(l)` | Transcript tokens + turns (schema-drift tolerant) |
| Qwen Code | `~/.qwen/tmp/**/*.json(l)` | Same as Gemini CLI |
| Pi | `~/.pi/agent/**` | Transcripts when present (`skills/` excluded) |
| DeepSeek | `~/.deepseek/**`, `~/.config/deepseek/**` | Transcripts when present |
| Cline | VSCode `globalStorage/*/tasks/*`, `~/.cline/tasks/*` | Usage counters + metadata when present |
| Windsurf | `~/.codeium/chat_state/*.pb` | Sessions/recency only (no local token counters) |

Where a tool exposes no local token counters, activity (sessions, turns, recency) is reported with zero tokens rather than invented figures.

## JSON output

`agent-tokens --json` emits a list of per-agent reports:

```json
[{ "agent_name": "Codex",
   "total_tokens": 7911802,
   "models": [{ "model_id": "gpt-5.6-terra", "input_tokens": 438500,
     "output_tokens": 31100, "reasoning_tokens": 10100,
     "cache_read_tokens": 4570000, "cache_write_tokens": 0,
     "total_tokens": 5051408, "session_count": 6, "turn_count": 12,
     "last_active": "2026-08-29 19:19:47" }],
   "recent_sessions": [{ "session_id": "rollout-2026-08-29...",
     "title": "wedtrack.in", "model_id": "gpt-5.6-terra",
     "input_tokens": 96200, "output_tokens": 9700, "reasoning_tokens": 4500,
     "cache_read_tokens": 720100, "cache_write_tokens": 0, "turn_count": 1,
     "total_tokens": 830600, "updated_at": "2026-08-29 19:19:47" }] }]
```

## Org leaderboard (token-maxing dashboard)

One-time setup per machine:

```bash
agent-tokens --onboard --email you@aganitha.ai --role engineering
agent-tokens --me
```

After that every `agent-tokens` run (any filter) pushes a full all-agent
snapshot to the org server in the background — HTTPS POST first, SSH
file-drop to own3 as fallback. Force it with `agent-tokens --sync`, skip it
with `agent-tokens --no-sync`. Sync never breaks local display.

Dashboard: `http://own3.aganitha.ai:8734` — Daily/Weekly overall, role-wise,
harness, and model boards (see `SKILL.md`, `docs/design.md`, `docs/PROS_CONS.md`).

Deploy (on own3, as root/sudoer):

```bash
sudo bash scripts/setup_shared_dir.sh
docker compose -f server/docker-compose.yml up -d --build
```

## Development

```bash
python3 -m unittest discover tests -v   # 74 tests, stdlib only
```

Layout: `src/agent_tokens/` holds `cli.py` (12-flag, registry-driven dispatch), `models.py` (dataclasses), `formatters.py` (terminal/JSON), and `providers/` (one module per agent plus shared `base.py`, `_util.py`, `transcripts.py`). Provider registry lives in `providers/__init__.py` (`ALL_PROVIDERS`, `FLAG_MAP`).

To add an agent: implement `BaseProvider` (`name`, `is_available`, `get_report`), register it in `ALL_PROVIDERS`/`FLAG_MAP`, add its flag to `cli.py:FILTER_FLAGS`, and cover it with fixtures under `tests/`.

## License

[MIT License](LICENSE) © 2026 Hriteek Roy
