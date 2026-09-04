"""Provider for the Pi coding agent's local session transcripts."""

import os
from typing import FrozenSet, List, Optional

from agent_tokens.models import AgentReport
from agent_tokens.providers.base import BaseProvider
from agent_tokens.providers.transcripts import (
    build_token_report,
    dedupe_chats,
    scan_transcript_dir,
)

_MODEL_ID = "pi-agent"

# Directories that hold install artefacts (skills, plugins), never sessions.
_NON_SESSION_SEGMENTS: FrozenSet[str] = frozenset(
    {"skills", "vendor", "plugins", "extensions", "node_modules"}
)


class PiProvider(BaseProvider):
    """Reads ``~/.pi/agent`` session transcripts (JSON/JSONL, if present).

    The on-disk transcript schema varies by Pi release; files are scanned
    defensively and any recognised token fields are aggregated. An empty
    install therefore reports no activity rather than failing.
    """

    def __init__(self, base_dir: Optional[str] = None):
        self.base_dir = base_dir or os.path.expanduser("~/.pi/agent")

    @property
    def name(self) -> str:
        return "Pi"

    def is_available(self) -> bool:
        return os.path.isdir(self.base_dir)

    def candidate_dirs(self) -> List[str]:
        cands = [self.base_dir]
        for sub in ("sessions", "transcripts", "history", "chats"):
            p = os.path.join(self.base_dir, sub)
            if os.path.isdir(p):
                cands.append(p)
        return cands

    def get_report(self, today_only: bool = False) -> Optional[AgentReport]:
        if not self.is_available():
            return None
        chats = []
        for directory in self.candidate_dirs():
            chats.extend(scan_transcript_dir(directory, today_only))
        # candidate_dirs() recurses, so dedupe and drop install artefacts
        # (skills metadata etc.).
        chats = dedupe_chats(chats, exclude_segments=_NON_SESSION_SEGMENTS)
        return build_token_report(self.name, _MODEL_ID, chats, default_title="pi-session")
