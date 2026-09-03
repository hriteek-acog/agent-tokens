# 🤖 agent-tokens

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python Version](https://img.shields.io/badge/python-3.9+-brightgreen.svg)](pyproject.toml)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux-lightgrey.svg)](#)

A production-grade, zero-config CLI analytics tool to track, audit, and aggregate token consumption across all your local AI coding agents: **OpenCode**, **Claude Code (CLI)**, and **Google Antigravity (AGY)**.

---

## ⚡ Why `agent-tokens`?

Modern AI software engineers use multiple coding assistants concurrently:
* **OpenCode** running local or cloud-hosted open-weights models (MuseSpark, Qwen 3.6 Coder, DeepSeek, Nemotron).
* **Claude Code** executing high-speed autonomous terminal workflows (Claude 3.5/3.7/4.5 Opus & Sonnet).
* **Google Antigravity (AGY)** orchestrating multi-agent systems and deep refactors (Gemini 3.8 Flash & Pro).

However, each tool records usage in disparate local databases, proprietary binary protocol buffers, or internal JSON state files. 

`agent-tokens` unifies them into a single, beautiful terminal dashboard and machine-readable JSON pipeline **without requiring any API keys** or network requests.

---

## ✨ Features

- 🔍 **Zero-Configuration**: Directly reads local SQLite databases, caches, and session logs.
- 🧠 **Deep Token Telemetry**: Tracks Input, Output, Reasoning/Thinking tokens, and Cache Read/Write hits.
- ⏱️ **Timeframe Filtering**: Filter by `--today` or inspect all-time historic token usage.
- 🎯 **Agent-Specific Views**: Filter by `--opencode`, `--claude`, or `--agy`.
- 📊 **Subagent & Session Tracking**: Displays turn counts, session titles, and timestamps for multi-agent workflows.
- 🚀 **Production Architecture**: Modular provider pattern (`BaseProvider`), strictly typed data models, unit-tested formatters.

---

## 💻 Output Preview

```text
════════════════════════════════════════════════════════════════════════════════
                    🤖 MULTI-AGENT TOKEN TRACKER (TODAY)
════════════════════════════════════════════════════════════════════════════════

► OPENCODE
────────────────────────────────────────────────────────────────────────────────
Model                              Sessions  Input      Output     Reasoning  Cache/Read  Total     
------------------------------------------------------------------------------------------------
muse-spark-1.3-contributor-free    8         13.98M     512.2K     188.7K     159.74M     174.22M   

  Recent Active Sessions:
  • Code review, improvement specs, docs cleanup  (muse-spark-1.3-contributor-free)
    Total: 29.41M (In: 419.7K, Out: 82.7K, Reasoning: 41.2K, Cache: 28.91M) 2026-09-04 05:12:20
  • New session - 2026-09-03T17:00:23.012Z        (muse-spark-1.3-contributor-free)
    Total: 115.62M (In: 11.46M, Out: 249.5K, Reasoning: 87.5K, Cache: 103.91M) 2026-09-04 05:07:54

► ANTIGRAVITY (AGY)
────────────────────────────────────────────────────────────────────────────────
Model                              Sessions  Input      Output     Reasoning  Cache/Read  Total     
------------------------------------------------------------------------------------------------
gemini-3.8-flash                   2         58.17M     608.9K     313.9K     4.70M       63.48M    

  Recent Active Sessions:
  • AI Browser Tab Manager                        (gemini-3.8-flash)
    Total: 36.11M (In: 33.32M, Out: 307.1K, Reasoning: 191.6K, Cache: 2.49M) 2026-09-03 22:53:40
  • Mac Storage Cleanup Guide                     (gemini-3.8-flash)
    Total: 27.60M (In: 25.08M, Out: 305.8K, Reasoning: 122.3K, Cache: 2.21M) 2026-09-03 21:45:19

════════════════════════════════════════════════════════════════════════════════
🎯 GRAND TOTAL TOKENS PROCESSED (TODAY): 237.94M (237,939,483 tokens)
════════════════════════════════════════════════════════════════════════════════
```

---

## 📦 Installation

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

---

## 🛠️ Usage

```bash
# View combined usage across all agents for TODAY
agent-tokens --today

# View all-time token metrics across every model and tool
agent-tokens

# Filter by a specific coding agent
agent-tokens --opencode
agent-tokens --claude
agent-tokens --agy

# Output as formatted JSON for dashboards, monitoring, or scripts
agent-tokens --json
```

---

## 🏗️ Architecture

```
agent-tokens/
├── src/agent_tokens/
│   ├── __init__.py
│   ├── cli.py             # CLI parser and dispatch loop
│   ├── models.py          # Strongly typed dataclasses (TokenStats, SessionInfo, AgentReport)
│   ├── formatters.py      # Terminal ANSI dashboard and JSON serializer
│   └── providers/
│       ├── base.py        # Abstract BaseProvider interface
│       ├── opencode.py    # Reads ~/.local/share/opencode/opencode.db
│       ├── claude.py      # Reads ~/.claude/stats-cache.json
│       └── antigravity.py # Parses ~/.gemini/antigravity-cli protobuf sessions
├── tests/                 # Unit test suite
├── pyproject.toml         # PEP 517/621 packaging metadata
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
        return os.path.exists("...")

    def get_report(self, today_only: bool = False) -> AgentReport:
        ...
```

---

## 🧪 Testing

Run the test suite with standard `unittest`:
```bash
python3 -m unittest discover tests
```

---

## 📄 License

[MIT License](LICENSE) © 2026 Hriteek Roy
