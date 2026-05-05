# CLAUDE.md — working conventions

Notes for Claude (and humans) when editing this repo.

## Voice
- Concise. No marketing language, no emojis in code, comments, commits, PRs.
- Prefer plain prose over headers in short replies.
- State decisions and tradeoffs directly. Don't hedge.

## Code
- Default to no comments. Add one only when the *why* is non-obvious
  (hidden constraint, workaround, surprising invariant).
- No "added for X" / "used by Y" comments. That belongs in commit messages.
- No backwards-compat shims, dead-code stubs, or unused-arg renames. Delete it.
- No premature abstraction. Three similar lines beat a wrong helper.
- Validate at boundaries (file load, CLI input, future API). Trust internal
  callers.

## Architecture
- `design.json` is the single source of truth. Generators are pure functions
  of `design.json` + library files. No artifact → document round-trips.
- Conversation history (when the agent lands in 0.2) lives in
  `sessions/<id>.jsonl`, never in `design.json`.
- Permissive mode: electrical/CSP violations surface in `warnings[]`,
  do not block generation. (Strict mode is a later toggle.)
- Secrets never go in `design.json`. Reference distributed-esphome's
  `secrets.yaml` via `!secret name`.

## Library files
- `library/components/<id>.yaml` carries electrical metadata that ESPHome
  doesn't (pins, passives, current draw, pull-up requirements) plus a
  Jinja2 ESPHome YAML template.
- `library/boards/<id>.yaml` carries board pinout, rails, and the
  PlatformIO board key.

## Tests
- Generator output is pinned to goldens in `tests/golden/`.
- When a golden changes intentionally, regenerate via the CLI and commit
  the new file in the same diff as the code change.

## TODOs
Use `# TODO(0.x):` to mark deferred work tied to a phase from `START.md`.
Plain `# TODO:` is fine for unscoped notes.

## What not to do
- No new top-level documentation files unless explicitly asked.
- No splitting `wirestudio/` into more packages until 0.2 needs them.
- No vendoring upstream ESPHome source. Schema-derived data only.
