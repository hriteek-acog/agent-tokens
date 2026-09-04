"""Provider for Windsurf (Codeium) chat activity.

Windsurf persists per-workspace chat snapshots as protobuf files under
``~/.codeium/chat_state/``. No token telemetry is exposed locally, so this
provider tracks conversation presence and recency: each chat-state file is
one session. Token columns read ``0`` — documented, not fabricated.
"""

import glob
import os
from datetime import datetime
from typing import List, Optional

from agent_tokens.models import AgentReport, TokenStats, SessionInfo
from agent_tokens.providers.base import BaseProvider

_MODEL_ID = "windsurf-chat"


class WindsurfProvider(BaseProvider):
    """Reads Windsurf ``~/.codeium/chat_state`` snapshot activity."""

    def __init__(self, state_dir: Optional[str] = None):
        self.state_dir = state_dir or os.path.expanduser("~/.codeium/chat_state")

    @property
    def name(self) -> str:
        return "Windsurf"

    def is_available(self) -> bool:
        return os.path.isdir(self.state_dir)

    def get_report(self, today_only: bool = False) -> Optional[AgentReport]:
        if not self.is_available():
            return None

        sessions: List[SessionInfo] = []
        last_active = ""
        today = datetime.now().date()
        try:
            files = sorted(glob.glob(os.path.join(self.state_dir, "*.pb")))
        except OSError:
            return AgentReport(agent_name=self.name)

        for path in files:
            try:
                mtime = datetime.fromtimestamp(os.stat(path).st_mtime)
            except OSError:
                continue
            if today_only and mtime.date() != today:
                continue
            stamp = mtime.strftime("%Y-%m-%d %H:%M:%S")
            last_active = max(last_active, stamp)
            base = os.path.basename(path)
            # Files look like codeium_chat_state_file_<path with _>.pb
            title = base
            prefix = "codeium_chat_state_file_"
            if title.startswith(prefix):
                title = title[len(prefix):]
            if title.endswith(".pb"):
                title = title[: -len(".pb")]
            title = title.replace("_", " ").strip()[:45] or base[:45]
            sessions.append(
                SessionInfo(
                    session_id=base[:36],
                    title=title,
                    model_id=_MODEL_ID,
                    updated_at=stamp,
                )
            )

        sessions.sort(key=lambda s: s.updated_at or "", reverse=True)
        models = []
        if sessions:
            models.append(
                TokenStats(
                    model_id=_MODEL_ID,
                    session_count=len(sessions),
                    last_active=last_active or None,
                )
            )
        return AgentReport(
            agent_name=self.name, models=models, recent_sessions=sessions[:25]
        )
