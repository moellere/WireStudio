"""Server-side design persistence.

Stores user-modified `design.json` documents at `designs/<id>.json` so the
UI can save and reload across browser refreshes. Distinct from
`examples/` (read-only, ships in the repo) and from `sessions/` (agent
conversation history, never carries design state).
"""

from wirestudio.designs.store import DesignStore, SavedDesignSummary

__all__ = ["DesignStore", "SavedDesignSummary"]
