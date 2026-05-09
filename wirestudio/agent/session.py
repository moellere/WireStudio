"""Append-only conversation history at sessions/<id>.jsonl.

Stores plain {role, content, timestamp} entries -- the within-turn
tool_use / tool_result ceremony stays in memory. The design itself is
*never* persisted in a session; the client owns it and ships it with
every turn.
"""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

SESSIONS_DIR_ENV_DEFAULT = Path(__file__).resolve().parent.parent.parent / "sessions"


def new_session_id() -> str:
    return secrets.token_urlsafe(8)


from typing import Optional, Protocol

class SessionStore(Protocol):
    def exists(self, session_id: str) -> bool: ...
    def load(self, session_id: str) -> list[dict]: ...
    def append(self, session_id: str, role: str, content: str) -> dict: ...

class FileSessionStore(SessionStore):

    """One-line-per-message JSONL files. Cheap, greppable, agent-friendly."""

    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = Path(root) if root else SESSIONS_DIR_ENV_DEFAULT
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, session_id: str) -> Path:
        if not session_id or "/" in session_id or ".." in session_id:
            raise ValueError(f"invalid session_id: {session_id!r}")
        return self.root / f"{session_id}.jsonl"

    def exists(self, session_id: str) -> bool:
        return self.path(session_id).exists()

    def load(self, session_id: str) -> list[dict]:
        path = self.path(session_id)
        if not path.exists():
            return []
        out: list[dict] = []
        with path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                out.append(json.loads(line))
        return out

    def append(self, session_id: str, role: str, content: str) -> dict:
        entry = {
            "role": role,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        with self.path(session_id).open("a") as f:
            f.write(json.dumps(entry) + "\n")
        return entry
