"""Provider for Qwen Code CLI chat transcripts.

Qwen Code is a Gemini-CLI fork and mirrors its on-disk layout under
``~/.qwen/tmp/<project-hash>/``. Transcript aggregation is shared with
:mod:`agent_tokens.providers.gemini_cli`.
"""

import os
from typing import Optional

from agent_tokens.models import AgentReport
from agent_tokens.providers.base import BaseProvider
from agent_tokens.providers.gemini_cli import build_report, scan_chat_dir

_MODEL_ID = "qwen-code"


class QwenProvider(BaseProvider):
    """Reads ``~/.qwen/tmp`` Qwen Code chat transcripts."""

    def __init__(self, tmp_dir: Optional[str] = None):
        self.tmp_dir = tmp_dir or os.path.expanduser("~/.qwen/tmp")

    @property
    def name(self) -> str:
        return "Qwen Code"

    def is_available(self) -> bool:
        return os.path.isdir(self.tmp_dir)

    def get_report(self, today_only: bool = False) -> Optional[AgentReport]:
        if not self.is_available():
            return None
        chats = scan_chat_dir(self.tmp_dir, today_only)
        return build_report(self.name, _MODEL_ID, chats)
