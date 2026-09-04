"""Provider for Google Gemini CLI chat transcripts.

Gemini CLI persists per-project chat files under ``~/.gemini/tmp/``.
Transcript parsing is shared with the other file-based providers via
:mod:`agent_tokens.providers.transcripts`.
"""

import os
from typing import Optional

from agent_tokens.models import AgentReport
from agent_tokens.providers.base import BaseProvider
from agent_tokens.providers.transcripts import build_token_report, scan_transcript_dir

_MODEL_ID = "gemini-cli"


class GeminiCliProvider(BaseProvider):
    """Reads ``~/.gemini/tmp`` Gemini CLI chat transcripts."""

    def __init__(self, tmp_dir: Optional[str] = None):
        self.tmp_dir = tmp_dir or os.path.expanduser("~/.gemini/tmp")

    @property
    def name(self) -> str:
        return "Gemini CLI"

    def is_available(self) -> bool:
        return os.path.isdir(self.tmp_dir)

    def get_report(self, today_only: bool = False) -> Optional[AgentReport]:
        if not self.is_available():
            return None
        chats = scan_transcript_dir(self.tmp_dir, today_only)
        return build_token_report(self.name, _MODEL_ID, chats, default_title="gemini-chat")
