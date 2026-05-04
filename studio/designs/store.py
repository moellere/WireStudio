"""File-backed design store.

One JSON file per saved design at `designs/<id>.json`. The id is derived
from the design's own `id` field (sanitized to the schema's pattern); the
filesystem mtime is the saved-at timestamp. The on-disk JSON is the raw
`design.json` document, no wrapper -- so a saved file can be loaded as an
example or fed to `python -m studio.generate` directly.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DESIGNS_DIR_DEFAULT = Path(__file__).resolve().parent.parent.parent / "designs"

# Schema's id pattern is `^[a-z0-9][a-z0-9-]*$`; we use a slightly looser
# sanitizer for storage (collapse runs of non-allowed chars to '-') and then
# enforce the schema-shaped result.
_ID_OK = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_ID_BAD = re.compile(r"[^a-z0-9-]+")


def sanitize_id(raw: str) -> str:
    """Coerce an arbitrary string into a schema-conformant design id.

    Lowercase, replace runs of non-allowed chars with '-', trim leading
    non-alphanumeric. Empty/invalid inputs raise ValueError.
    """
    if not raw or not isinstance(raw, str):
        raise ValueError("design id must be a non-empty string")
    s = raw.strip().lower()
    s = _ID_BAD.sub("-", s)
    s = s.strip("-")
    if not s or not _ID_OK.match(s):
        raise ValueError(f"could not derive a valid design id from {raw!r}")
    return s


@dataclass
class SavedDesignSummary:
    id: str
    name: str
    description: str
    board_library_id: str
    chip_family: str
    saved_at: str
    component_count: int


class DesignStore:
    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = Path(root) if root else DESIGNS_DIR_DEFAULT
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, design_id: str) -> Path:
        # Reject traversal even though sanitize_id should prevent it.
        if not design_id or "/" in design_id or ".." in design_id or "\\" in design_id:
            raise ValueError(f"invalid design id: {design_id!r}")
        return self.root / f"{design_id}.json"

    def exists(self, design_id: str) -> bool:
        return self.path(design_id).exists()

    def list(self) -> list[SavedDesignSummary]:
        out: list[SavedDesignSummary] = []
        for p in sorted(self.root.glob("*.json")):
            try:
                data = json.loads(p.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            saved_at = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat()
            board = data.get("board") or {}
            components = data.get("components") or []
            out.append(SavedDesignSummary(
                id=p.stem,
                name=str(data.get("name", "")),
                description=str(data.get("description", "")),
                board_library_id=str(board.get("library_id", "")),
                chip_family=str(board.get("mcu", "")),
                saved_at=saved_at,
                component_count=len(components),
            ))
        # Newest first.
        out.sort(key=lambda s: s.saved_at, reverse=True)
        return out

    def load(self, design_id: str) -> dict:
        path = self.path(design_id)
        if not path.exists():
            raise FileNotFoundError(f"no saved design with id {design_id!r}")
        return json.loads(path.read_text())

    def save(self, design: dict, design_id: Optional[str] = None) -> tuple[str, str]:
        """Write the design to disk. Returns (id, saved_at).

        If `design_id` is None, derives it from `design['id']`. Overwrites
        any existing file with the same id; the on-disk timestamp updates
        to now.
        """
        if design_id is None:
            raw = design.get("id")
            if not raw:
                raise ValueError("design has no `id` field; pass design_id explicitly")
            design_id = sanitize_id(str(raw))
        else:
            design_id = sanitize_id(design_id)
        path = self.path(design_id)
        path.write_text(json.dumps(design, indent=2, default=str))
        saved_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
        return design_id, saved_at

    def delete(self, design_id: str) -> bool:
        path = self.path(design_id)
        if not path.exists():
            return False
        path.unlink()
        return True
