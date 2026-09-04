"""Provider for the Pi coding agent's local session transcripts."""

import os
from typing import List, Optional

from agent_tokens.models import AgentReport
from agent_tokens.providers.base import BaseProvider
from agent_tokens.providers.gemini_cli import build_report, scan_chat_dir

_MODEL_ID = "pi-agent"

# Directories that hold install artefacts (skills, plugins), never sessions.
_NON_SESSION_SEGMENTS = {"skills", "vendor", "plugins", "extensions", "node_modules"}


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
        for d in self.candidate_dirs():
            chats.extend(scan_chat_dir(d, today_only))
        # scan_chat_dir(base) already recurses into subdirs; dedupe by path
        # and drop install artefacts (skills metadata etc.).
        seen = set()
        uniq = []
        for c in chats:
            parts = set(c["path"].split(os.sep))
            if parts & _NON_SESSION_SEGMENTS:
                continue
            if c["path"] not in seen:
                seen.add(c["path"])
                uniq.append(c)
        return build_report(self.name, _MODEL_ID, uniq)
