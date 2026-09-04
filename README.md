# agent-tokens

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python Version](https://img.shields.io/badge/python-3.9+-brightgreen.svg)](pyproject.toml)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux-lightgrey.svg)](#)

See your AI coding-agent token usage in the terminal — and compete on the org leaderboard. Covers OpenCode, Claude Code, Antigravity, Codex, Copilot, Cursor, Gemini CLI, Qwen Code, Pi, DeepSeek, Cline, Windsurf.

Leaderboard: **https://token-leaderboard.own3.aganitha.ai** (Daily / Weekly, overall + role-wise + harness + model boards)

## Get started (3 steps, ~2 min)

Prereqs: Python 3.9+, an `@aganitha.ai` email, and `ssh own3` access.

```bash
git clone https://github.com/hriteek-acog/agent-tokens.git
cd agent-tokens
bash scripts/install.sh
agent-tokens --onboard --email you@aganitha.ai --role engineering
agent-tokens doctor
```

`doctor` checks install, identity, server, and sync path — fix any `FAIL` line it prints. Roles: `engineering research design product data qa devops intern other`.

## Daily use

```bash
agent-tokens            # your usage (+ auto-syncs to the leaderboard)
agent-tokens --today    # today's activity only (+ auto-syncs)
agent-tokens --sync     # force a push now
```

Every run syncs in the background and never breaks local display. If `agent-tokens` is ever "command not found", re-run `bash scripts/install.sh`.

## Reference

```bash
agent-tokens --codex          # one agent (--opencode --claude --agy --copilot
                              # --cursor --gemini --qwen --pi --deepseek
                              # --cline --windsurf); sync still covers all
agent-tokens --today --json   # machine-readable output
agent-tokens --no-sync        # display without pushing
agent-tokens --me             # show your linked identity
agent-tokens --no-color        # plain output (also respects NO_COLOR=1)
```

Totals = input + output + reasoning + cache reads + cache writes. Tools without local token counters report activity with zero tokens — nothing is invented.

## Admin: deploy the leaderboard server (own3)

```bash
bash scripts/setup_shared_dir.sh
docker compose -f server/docker-compose.yml up -d --build
```

No ports are published; the reverse proxy picks the container up by its labels. Details: `docs/design.md`, trade-offs: `docs/PROS_CONS.md`, agent skill: `SKILL.md`.

## Development

```bash
python3 -m unittest discover tests   # stdlib only
```

To add an agent: implement `BaseProvider`, register in `providers/__init__.py` (`ALL_PROVIDERS`/`FLAG_MAP`), add the flag in `cli.py`, cover with fixtures under `tests/`.

## License

[MIT License](LICENSE) © 2026 Hriteek Roy
