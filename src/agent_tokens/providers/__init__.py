"""Agent providers module: 12-agent registry."""

from agent_tokens.providers.base import BaseProvider
from agent_tokens.providers.opencode import OpenCodeProvider
from agent_tokens.providers.claude import ClaudeCodeProvider
from agent_tokens.providers.antigravity import AntigravityProvider
from agent_tokens.providers.codex import CodexProvider
from agent_tokens.providers.copilot import CopilotProvider
from agent_tokens.providers.cursor import CursorProvider
from agent_tokens.providers.gemini_cli import GeminiCliProvider
from agent_tokens.providers.qwen import QwenProvider
from agent_tokens.providers.pi import PiProvider
from agent_tokens.providers.deepseek import DeepSeekProvider
from agent_tokens.providers.cline import ClineProvider
from agent_tokens.providers.windsurf import WindsurfProvider

__all__ = [
    "BaseProvider",
    "OpenCodeProvider",
    "ClaudeCodeProvider",
    "AntigravityProvider",
    "CodexProvider",
    "CopilotProvider",
    "CursorProvider",
    "GeminiCliProvider",
    "QwenProvider",
    "PiProvider",
    "DeepSeekProvider",
    "ClineProvider",
    "WindsurfProvider",
    "ALL_PROVIDERS",
    "FLAG_MAP",
]

# Canonical provider set, in dashboard display order.
ALL_PROVIDERS = (
    OpenCodeProvider,
    ClaudeCodeProvider,
    AntigravityProvider,
    CodexProvider,
    CopilotProvider,
    CursorProvider,
    GeminiCliProvider,
    QwenProvider,
    PiProvider,
    DeepSeekProvider,
    ClineProvider,
    WindsurfProvider,
)

# Maps CLI filter flags (without the leading dashes) to provider classes.
FLAG_MAP = {
    "opencode": OpenCodeProvider,
    "claude": ClaudeCodeProvider,
    "agy": AntigravityProvider,
    "codex": CodexProvider,
    "copilot": CopilotProvider,
    "cursor": CursorProvider,
    "gemini": GeminiCliProvider,
    "qwen": QwenProvider,
    "pi": PiProvider,
    "deepseek": DeepSeekProvider,
    "cline": ClineProvider,
    "windsurf": WindsurfProvider,
}
