# 🤖 agent-tokens

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python Version](https://img.shields.io/badge/python-3.9+-brightgreen.svg)](pyproject.toml)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux-lightgrey.svg)](#)

A production-grade, zero-config CLI analytics tool to track, audit, and aggregate token consumption across all your local AI coding agents: **OpenCode**, **Claude Code (CLI)**, **Google Antigravity (AGY)**, **OpenAI Codex**, **GitHub Copilot**, **Cursor**, **Gemini CLI**, **Qwen Code**, **Pi**, **DeepSeek harnesses**, **Cline**, and **Windsurf**.

---

## ⚡ Why `agent-tokens`?

Modern AI software engineers use multiple coding assistants concurrently:
* **OpenCode** running local or cloud-hosted open-weights models (MuseSpark, Qwen 3.6 Coder, DeepSeek, Nemotron).
* **Claude Code** executing high-speed autonomous terminal workflows (Claude 3.5/3.7/4.5 Opus & Sonnet).
* **Google Antigravity (AGY)** orchestrating multi-agent systems and deep refactors (Gemini 3.8 Flash & Pro).
* **OpenAI Codex** (CLI/Desktop rollouts), **GitHub Copilot** (CLI harness + chat extension), **Cursor**, **Gemini CLI**, **Qwen Code**, **Pi**, **DeepSeek** harnesses, **Cline**, and **Windsurf**.

However, each tool records usage in disparate local databases, proprietary binary protocol buffers, or internal JSON state files.

`agent-tokens` unifies them into a single, beautiful terminal dashboard and machine-readable JSON pipeline **without requiring any API keys** or network requests. All databases are opened **read-only**, so running agents are never locked or disturbed, and one corrupt store can never sink the whole run (per-provider fault isolation with stderr warnings).

---

## ✨ Features

- 🔍 **Zero-Configuration**: Directly reads local SQLite databases, caches, and session logs.
- 🧠 **Deep Token Telemetry**: Tracks Input, Output, Reasoning/Thinking tokens, and Cache Read **+ Write** hits.
- 🧮 **Honest Totals**: `total = input + output + reasoning + cache_read + cache_write`. The `Cache` column displays read + write combined so the row always adds up.
- ⏱️ **Timeframe Filtering**: Filter by `--today` or inspect all-time historic token usage.
- 🎯 **Agent-Specific Views**: Filter by `--opencode`, `--claude`, `--agy`, `--codex`, `--copilot`, `--cursor`, `--gemini`, `--qwen`, `--pi`, `--deepseek`, `--cline`, or `--windsurf` (combinable with `--today` and `--json`).
- 📊 **Session Tracking**: Displays the most recently active sessions for every agent with local history (OpenCode, Antigravity, Codex, Copilot, Cursor, Cline, Windsurf, Gemini/Qwen/Pi/DeepSeek transcripts), with turn counts where available.
- 🎨 **Terminal-Friendly**: ANSI dashboard with `--no-color` flag and `NO_COLOR` env-var support for clean pipes and logs.
- 📦 **Machine-Readable**: `--json` emits the full report (models + sessions) for dashboards and scripts.
- 🛡️ **Fault Isolation**: Each provider is queried independently; failures print a `warning:` to stderr and the remaining providers still render.

---

## 💻 Output Preview

(Trimmed — the live dashboard renders one section per available agent across all 12 providers.)

```text
════════════════════════════════════════════════════════════════════════════════
                    🤖 MULTI-AGENT TOKEN TRACKER (TODAY)
════════════════════════════════════════════════════════════════════════════════

► OPENCODE
────────────────────────────────────────────────────────────────────────────────
Model                              Sessions  Input      Output     Reasoning  Cache       Total
------------------------------------------------------------------------------------------------
muse-spark-1.3-contributor-free    9         14.04M     530.7K     194.2K     160.93M     175.70M

  Recent Active Sessions:
  • Code review, docs update and GitHub push      (muse-spark-1.3-contributor-free)
    Total: 1.28M (In: 66.1K, Out: 18.5K, Reasoning: 5.5K, Cache: 1.19M) 2026-09-04 05:20:47
  • New session - 2026-09-03T17:00:23.012Z        (muse-spark-1.3-contributor-free)
    Total: 115.71M (In: 11.46M, Out: 249.5K, Reasoning: 87.5K, Cache: 103.91M) 2026-09-04 05:07:54

► CLAUDE CODE
────────────────────────────────────────────────────────────────────────────────
  No activity recorded for this timeframe.

► ANTIGRAVITY (AGY)
────────────────────────────────────────────────────────────────────────────────
Model                          Sessions Turns  Input     Output    Reason   Cache      Total
------------------------------------------------------------------------------------------------
gemini-3.8-flash               3        545    67.60M    718.3K    363.1K   5.88M      74.56M

  Recent Active Sessions:
  • AI Browser Tab Manager                        (gemini-3.8-flash)
    Total: 36.30M (In: 33.32M, Out: 307.1K, Reasoning: 191.6K, Cache: 2.49M) · 233 turns 2026-09-03 22:53:40

════════════════════════════════════════════════════════════════════════════════
🎯 GRAND TOTAL TOKENS PROCESSED (TODAY): 250.49M (250,493,444 tokens)
════════════════════════════════════════════════════════════════════════════════
```

> The `Turns` column appears only for providers that report generation turns (currently Antigravity). `Cache` = cache reads + cache writes.

---

## 📦 Installation

### Requirements

- Python 3.9+
- macOS or Linux (paths below are `~`-relative; no network access needed)

### From Source
```bash
git clone https://github.com/hritxx/agent-tokens.git
cd agent-tokens
pip install -e .
```

### Direct Pip Install
```bash
pip install git+https://github.com/hritxx/agent-tokens.git
```

Verify:
```bash
agent-tokens --version
```

---

## 🛠️ Usage

```bash
# View combined usage across all agents for TODAY
agent-tokens --today

# View all-time token metrics across every model and tool
agent-tokens

# Filter by a specific coding agent (combinable)
agent-tokens --opencode
agent-tokens --claude
agent-tokens --agy
agent-tokens --codex
agent-tokens --copilot
agent-tokens --cursor
agent-tokens --gemini --qwen
agent-tokens --pi --deepseek
agent-tokens --cline --windsurf
agent-tokens --today --codex

# Output as formatted JSON for dashboards, monitoring, or scripts
agent-tokens --json
agent-tokens --today --json

# Disable ANSI colors (or export NO_COLOR=1)
agent-tokens --no-color
agent-tokens --version
```

Exit code is `0` on success. When nothing matches, the dashboard states `No token activity found for this timeframe` and the checked provider names are echoed to stderr.

---

## 🔌 Data Sources & Privacy

Everything stays on your machine. No API keys, no network calls.

| Agent | Source | What's read |
|---|---|---|
| OpenCode | `~/.local/share/opencode/opencode.db` (SQLite, `session` table, read-only) | `tokens_input/output/reasoning/cache_read/cache_write`, `time_updated` (epoch ms) |
| Claude Code | `~/.claude/stats-cache.json` | `modelUsage` breakdown (all-time); `dailyModelTokens` totals (today) |
| Antigravity | `~/.gemini/antigravity-cli/conversations/*.db` + `conversation_summaries.db` (read-only) | `gen_metadata` protobuf blobs (model, input/output/cached/reasoning), titles/mtimes |
| Codex | `~/.codex/sessions/**/rollout-*.jsonl` | Cumulative `token_count` events (input/cached/output/reasoning), `turn_context` model + turns; older lump-`total_tokens` rollouts attributed to input |
| Copilot | `~/.copilot/session-state/*/events.jsonl` + VSCode `globalStorage/github.copilot-chat/session-store.db` (read-only) | Harness model + `currentTokens` estimate (as input) + turns; chat-extension sessions/turns (no local token split) |
| Cursor | `~/Library/Application Support/Cursor/User/workspaceStorage/*` (or `~/.config/Cursor/...` on Linux) | Workspace sessions + recency (no local token telemetry — tokens read `0`) |
| Gemini CLI | `~/.gemini/tmp/**/*.json[ l]` | Chat transcripts: turns + any recognised token fields |
| Qwen Code | `~/.qwen/tmp/**/*.json[ l]` | Same fork layout as Gemini CLI |
| Pi | `~/.pi/agent/**` (sessions/transcripts/history) | Transcript files if present (`skills/` artefacts excluded) |
| DeepSeek | `~/.deepseek/**`, `~/.config/deepseek/**` | Harness transcripts if present |
| Cline | VSCode `globalStorage/{saoudrizwan.claude-dev,cline.cline}/tasks/*/`, `~/.cline/tasks/*` | `api_conversation_history.json` (`tokensIn/Out`, `cacheReads/Writes`) + task metadata model/title |
| Windsurf | `~/.codeium/chat_state/*.pb` | Chat snapshot presence + recency (protobuf carries no local token counts — tokens read `0`) |

> Telemetry fidelity differs per vendor: where a tool exposes no local token counters (Cursor, Windsurf, parts of Copilot/Cline), `agent-tokens` reports real session/turn activity with `0` tokens rather than inventing numbers.

---

## ⚠️ Known Limitations

- **Claude Code `--today` breakdown is estimated.** `dailyModelTokens` (schema v5) records only per-model *totals*; the input/output/cache split is apportioned from each model's all-time `modelUsage` ratios so the total stays exact. Legacy detailed day-entries are still parsed when present.
- **Claude Code has no per-session view.** The cache exposes model aggregates only, so `Sessions` reads `0` and no recent-session list is shown for this provider.
- **Antigravity model attribution:** multi-model conversations are attributed to their most frequent model; blobs without a model field surface as `gemini-unknown` rather than being silently merged into `gemini`.
- **Antigravity recency:** sessions sort by last-modified time (file mtime is the fallback when the summaries DB lacks a timestamp), tolerating local/UTC date skew for `--today`.
- **Reasoning accounting:** reasoning tokens are counted in totals (they are reported outside output tokens by OpenCode/AGY). Totals therefore run slightly higher than versions ≤ 1.0.0, which excluded them.
- **Codex older rollouts:** sessions that only record a lump `total_tokens` (no per-category split, no `turn_context`) are attributed to input with model `codex-unknown`; token-count events double as the turn fallback.
- **Copilot tokens are estimates.** The harness reports only a shutdown `currentTokens` context size (recorded as input); the chat-extension store has no token fields at all — sessions/turns are exact, tokens are approximate.
- **Cursor / Windsurf expose no local token counters.** Sessions and recency are real; token columns read `0` by design.
- **Transcript-schema drift (Gemini CLI, Qwen, Pi, DeepSeek, Cline):** parsers aggregate recognised token fields defensively; unrecognised files count as sessions with zero tokens rather than failing.

---

## 📤 JSON Schema

`agent-tokens --json` emits a list of agent reports:

```json
[
  {
    "agent_name": "OpenCode",
    "total_tokens": 175700000,
    "models": [
      {
        "model_id": "muse-spark-1.3-contributor-free",
        "input_tokens": 14040000,
        "output_tokens": 530700,
        "reasoning_tokens": 194200,
        "cache_read_tokens": 160930000,
        "cache_write_tokens": 0,
        "total_tokens": 175700000,
        "session_count": 9,
        "turn_count": 0,
        "last_active": "2026-09-04 05:20:47"
      }
    ],
    "recent_sessions": [
      {
        "session_id": "s1",
        "title": "Code review, docs update and GitHub push",
        "model_id": "muse-spark-1.3-contributor-free",
        "input_tokens": 66100,
        "output_tokens": 18500,
        "reasoning_tokens": 5500,
        "cache_read_tokens": 1190000,
        "cache_write_tokens": 0,
        "turn_count": 0,
        "total_tokens": 1280000,
        "updated_at": "2026-09-04 05:20:47"
      }
    ]
  }
]
```

---

## 🏗️ Architecture

```
agent-tokens/
├── src/agent_tokens/
│   ├── __init__.py          # Version (1.2.0)
│   ├── cli.py               # 12-flag CLI parser + registry-driven, fault-isolated dispatch
│   ├── models.py            # Strongly typed dataclasses (TokenStats, SessionInfo, AgentReport); totals include reasoning + cache write
│   ├── formatters.py        # ANSI dashboard (NO_COLOR aware, per-provider Turns column) and JSON serializer
│   └── providers/
│       ├── base.py          # Abstract BaseProvider interface
│       ├── _util.py         # Shared helpers (safe_int, read-only connect, today checks)
│       ├── __init__.py      # ALL_PROVIDERS registry + FLAG_MAP (12 agents)
│       ├── opencode.py      # Reads ~/.local/share/opencode/opencode.db (read-only, parameterized, all-scope recent sessions)
│       ├── claude.py        # Reads ~/.claude/stats-cache.json (v5 totals + legacy schema, proportional today split)
│       ├── antigravity.py   # Parses ~/.gemini/antigravity-cli protobuf sessions (robust proto decoder, read-only)
│       ├── codex.py         # Parses ~/.codex/sessions rollout JSONL (cumulative token_count + turn_context)
│       ├── copilot.py       # Harness events.jsonl + chat session-store.db (estimates documented)
│       ├── cursor.py        # Cursor workspaceStorage activity (no local token telemetry)
│       ├── gemini_cli.py    # Gemini CLI transcripts + shared scan/build helpers
│       ├── qwen.py          # Qwen Code transcripts (shared fork-layout helpers)
│       ├── pi.py            # Pi agent transcripts (skills artefacts excluded)
│       ├── deepseek.py      # DeepSeek harness transcripts (~/.deepseek, ~/.config/deepseek)
│       ├── cline.py         # Cline task histories (tokensIn/Out, cacheReads/Writes)
│       └── windsurf.py      # Windsurf chat_state presence + recency
├── tests/
│   ├── test_models.py       # Totals, coercion, defaults
│   ├── test_formatters.py   # Number formatting, empty/no-color/cache/turns cases
│   ├── test_providers.py    # SQLite fixtures, v5 regression, proto decoder, today-filter fallback
│   ├── test_new_providers.py# Codex/Copilot/Cursor/Gemini/Qwen/Pi/DeepSeek/Cline/Windsurf fixtures
│   └── test_cli.py          # Registry size, flags, failure isolation, JSON + empty-state behavior
├── pyproject.toml           # PEP 517/621 packaging metadata
└── README.md
```

### Adding New Providers
Implement `BaseProvider` under `src/agent_tokens/providers/`:
```python
from agent_tokens.providers.base import BaseProvider
from agent_tokens.models import AgentReport

class CustomAgentProvider(BaseProvider):
    @property
    def name(self) -> str:
        return "CustomAgent"

    def is_available(self) -> bool:
        import os
        return os.path.exists("...")

    def get_report(self, today_only: bool = False) -> AgentReport | None:
        ...
```

Then register it in `providers/__init__.py` (`ALL_PROVIDERS` + `FLAG_MAP`) and add its filter flag to `cli.py:FILTER_FLAGS`.

---

## 🧪 Testing

Run the full suite with standard `unittest` (64 tests):

```bash
python3 -m unittest discover tests -v
```

Coverage highlights: model totals incl. reasoning/cache-write, `None`/float coercion, OpenCode today/all-time filtering + missing-table handling, Claude v5 totals regression + proportional split, Antigravity proto decoder (fixed-width skip, truncation guard) + file-mtime today fallback, Codex rollout parsing (cached-input split, lump-total + turns fallbacks), Copilot harness + chat-store fixtures, Cursor/Gemini/Qwen/Pi/DeepSeek/Cline/Windsurf fixtures, formatter empty/no-color/cache/turns states, and CLI registry + failure isolation.

---

## 🩺 Troubleshooting

| Symptom | Cause / Fix |
|---|---|
| `No token activity found for this timeframe` | Normal with `--today` on a quiet day, or when a data store is absent. Drop `--today` or check the paths in Data Sources. |
| `warning: <Agent> report failed ...; skipping.` | That provider's store was unreadable/corrupt. The remaining providers still render; inspect the file permissions or JSON validity. |
| Claude `--today` shows no activity but all-time is huge | Expected if the last activity predates today — the v5 day-total for today is simply absent. |
| Garbled output when piping | Use `--no-color` or `export NO_COLOR=1`. |
| `gemini-unknown` row | Antigravity blobs without a model field. More honest than merging into `gemini`; safe to ignore or report upstream. |
| `0`-token rows for Cursor/Windsurf | By design — those tools expose no local token counters; sessions/turns are still tracked. |
| `codex-unknown` row | Older Codex rollouts without `turn_context` model records; lump totals preserved under this label. |

---

## 📝 Changelog

### 1.2.0
- **Added:** 12-agent coverage — new providers for Codex (`--codex`, rollout JSONL with cached-input split + lump-total/turn fallbacks), Copilot (`--copilot`, harness estimates + chat session store), Cursor (`--cursor`, workspace activity), Gemini CLI (`--gemini`), Qwen Code (`--qwen`), Pi (`--pi`, skills artefacts excluded), DeepSeek (`--deepseek`), Cline (`--cline`, usage counters + metadata), Windsurf (`--windsurf`, chat presence).
- **Added:** central `ALL_PROVIDERS` registry + `FLAG_MAP`; CLI dispatches registry-driven; shared `providers/_util.py` helpers.
- **Tests:** suite grown 36 → 64 (`test_new_providers.py` + registry-aware `test_cli.py`).
- **Fixed:** Claude Code `--today` always empty — v5 `dailyModelTokens` (`tokensByModel` totals) now parsed with proportional input/output/cache split; totals exact.
- **Fixed:** `total_tokens` now includes reasoning tokens (both `TokenStats` and `SessionInfo`); `SessionInfo` gains `cache_write_tokens` + `turn_count`.
- **Fixed:** OpenCode `tokens_cache_write` was never read; recent sessions now shown for all-time as well as `--today`; read-only connections, parameterized queries, missing-table guard.
- **Fixed:** Antigravity proto decoder aborted on 64/32-bit fields (now skipped), read-only connections with guaranteed close, file-mtime fallback for `--today`, multi-model sessions attributed to modal model, recency sorting.
- **Added:** `--version`, `--no-color` (+ `NO_COLOR` support), per-report `Turns` column, combined `Cache` (read + write) column, empty-state messaging, per-provider fault isolation.
- **Tests:** suite grown 5 → 36 (providers, formatters, CLI).

### 1.0.0
- Initial release: multi-agent tracking CLI across OpenCode, Claude Code, and Antigravity.

---

## 📄 License

[MIT License](LICENSE) © 2026 Hriteek Roy
