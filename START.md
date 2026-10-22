# wirestudio — resuming work

This file was the project's working log through 0.x. The decisions it
held are now reference pages under `docs/`; the log itself is in git
history (`git log --follow -p -- START.md`).

## Resuming a session

1. Read [`docs/roadmap.md`](docs/roadmap.md): what 1.0 promises, what
   has landed, and what is still open or blocked.
2. Read the `[Unreleased]` section of [`CHANGELOG.md`](CHANGELOG.md)
   and `git log --oneline -20` for what shipped most recently.
3. Check the open GitHub issues for work outside the roadmap.
4. Get a working tree: `pip install -e .[dev]` and
   `cd web && npm install`. `python -m pytest -q` and
   `cd web && npm test` should pass.

## Where things are

- [`docs/architecture.md`](docs/architecture.md): the design decisions
  every change is held to (single source of truth, no LLM in a compile
  path, the framework / build / network-server axes, the library split).
- [`docs/design-schema.md`](docs/design-schema.md): every `design.json`
  field, generated from the schema.
- [`docs/library.md`](docs/library.md): the boards and components, and
  how the library is sourced.
- [`CLAUDE.md`](CLAUDE.md): working conventions.
- [`CONTRIBUTING.md`](CONTRIBUTING.md): the bar a change has to clear.
