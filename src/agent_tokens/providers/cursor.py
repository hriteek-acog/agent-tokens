"""Provider for Cursor IDE agent activity.

Cursor exposes no local token telemetry (workspace state holds UI state,
not usage counts), so this provider tracks workspace sessions and
recency: each ``workspaceStorage`` entry is one workspace session.
Token columns will read ``0`` — documented, not fabricated.
"""

import json
import os
from datetime import datetime
from typing import List, Optional
from urllib.parse import unquote, urlparse

from agent_tokens.models import AgentReport, SessionInfo
from agent_tokens.providers.base import BaseProvider
from agent_tokens.providers.transcripts import build_activity_report

_MODEL_ID = "cursor-composer"


def _workspace_title(ws_json: str, fallback: str) -> str:
    try:
        with open(ws_json, "r", encoding="utf-8", errors="ignore") as f:
            data = json.load(f)
        folder = data.get("folder", "")
        if folder:
            path = unquote(urlparse(folder).path)
            base = os.path.basename(path.rstrip("/"))
            if base:
                return base
    except (OSError, ValueError):
        pass
    return fallback


class CursorProvider(BaseProvider):
    """Reads Cursor's ``workspaceStorage`` directory activity."""

    def __init__(self, storage_dir: Optional[str] = None):
        self.storage_dir = storage_dir or os.path.expanduser(
            "~/Library/Application Support/Cursor/User/workspaceStorage"
        )
        # Fallback used on Linux: ~/.config/Cursor/User/workspaceStorage
        self.alt_dir = os.path.expanduser("~/.config/Cursor/User/workspaceStorage")

    @property
    def name(self) -> str:
        return "Cursor"

    def _root(self) -> Optional[str]:
        if os.path.isdir(self.storage_dir):
            return self.storage_dir
        if os.path.isdir(self.alt_dir):
            return self.alt_dir
        return None

    def is_available(self) -> bool:
        return self._root() is not None

    def get_report(self, today_only: bool = False) -> Optional[AgentReport]:
        root = self._root()
        if root is None:
            return None

        sessions: List[SessionInfo] = []
        today = datetime.now().date()
        try:
            entries = sorted(os.listdir(root))
        except OSError:
            return AgentReport(agent_name=self.name)

        for entry in entries:
            full = os.path.join(root, entry)
            if not os.path.isdir(full):
                continue
            try:
                mtime = datetime.fromtimestamp(os.stat(full).st_mtime)
            except OSError:
                continue
            if today_only and mtime.date() != today:
                continue
            stamp = mtime.strftime("%Y-%m-%d %H:%M:%S")
            title = _workspace_title(os.path.join(full, "workspace.json"), entry[:18])
            sessions.append(
                SessionInfo(
                    session_id=entry,
                    title=title,
                    model_id=_MODEL_ID,
                    updated_at=stamp,
                )
            )

        return build_activity_report(self.name, _MODEL_ID, sessions)
