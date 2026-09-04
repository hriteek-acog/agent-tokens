"""Provider for DeepSeek harness session transcripts.

Covers the common local layouts used by DeepSeek CLI-style harnesses:
``~/.deepseek`` and ``~/.config/deepseek`` (JSON/JSONL transcripts with
usage fields). Schemas vary, so files are scanned defensively and any
recognised token fields aggregated; missing layouts simply report no
activity.
"""

import os
from typing import List, Optional

from agent_tokens.models import AgentReport
from agent_tokens.providers.base import BaseProvider
from agent_tokens.providers.transcripts import (
    build_token_report,
    dedupe_chats,
    scan_transcript_dir,
)

_MODEL_ID = "deepseek"

_CANDIDATES = ("~/.deepseek", "~/.config/deepseek")


class DeepSeekProvider(BaseProvider):
    """Reads DeepSeek harness transcript directories, when present."""

    def __init__(self, base_dirs: Optional[List[str]] = None):
        if base_dirs is None:
            self.base_dirs = [os.path.expanduser(p) for p in _CANDIDATES]
        else:
            self.base_dirs = base_dirs

    @property
    def name(self) -> str:
        return "DeepSeek"

    def is_available(self) -> bool:
        return any(os.path.isdir(d) for d in self.base_dirs)

    def get_report(self, today_only: bool = False) -> Optional[AgentReport]:
        if not self.is_available():
            return None
        chats = []
        for directory in self.base_dirs:
            chats.extend(scan_transcript_dir(directory, today_only))
        chats = dedupe_chats(chats)
        return build_token_report(self.name, _MODEL_ID, chats, default_title="deepseek-session")
