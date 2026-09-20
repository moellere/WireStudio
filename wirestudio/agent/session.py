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
from typing import Optional, Protocol

SESSIONS_DIR_ENV_DEFAULT = Path(__file__).resolve().parent.parent.parent / "sessions"


def new_session_id() -> str:
    return secrets.token_urlsafe(8)


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


class SqliteSessionStore(SessionStore):
    """Append-only history in one SQLite file; same entries as the JSONL
    store, one row each, in insertion order."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS messages ("
                "seq INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, "
                "role TEXT NOT NULL, content TEXT NOT NULL, timestamp TEXT NOT NULL)"
            )
            db.execute("CREATE INDEX IF NOT EXISTS messages_session ON messages (session_id, seq)")

    def _connect(self):
        import sqlite3
        db = sqlite3.connect(self.path, timeout=10)
        db.execute("PRAGMA journal_mode=WAL")
        return db

    def exists(self, session_id: str) -> bool:
        with self._connect() as db:
            return db.execute(
                "SELECT 1 FROM messages WHERE session_id = ? LIMIT 1", (session_id,)).fetchone() is not None

    def load(self, session_id: str) -> list[dict]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT role, content, timestamp FROM messages WHERE session_id = ? ORDER BY seq",
                (session_id,)).fetchall()
        return [{"role": r, "content": c, "timestamp": t} for r, c, t in rows]

    def append(self, session_id: str, role: str, content: str) -> dict:
        if not session_id:
            raise ValueError("invalid session_id: ''")
        entry = {
            "role": role,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        with self._connect() as db:
            db.execute(
                "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
                (session_id, role, content, entry["timestamp"]),
            )
        return entry
