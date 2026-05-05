"""Claude tool-using agent for design.json edits.

The agent layer is intentionally small: tools mutate a per-turn working copy
of `design`, the manual agentic loop runs until the model emits `end_turn`,
and the updated design is returned alongside the assistant's text. Conversation
history persists in `sessions/<id>.jsonl`; the design itself is owned by the
client and arrives with each turn.
"""
