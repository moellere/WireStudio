# esphome-studio

Agent-driven ESPHome device design tool. Describe a goal (or pick parts);
get an ESPHome YAML, an ASCII wiring diagram, and a BOM.

Sister project to [`weirded/distributed-esphome`](https://github.com/weirded/distributed-esphome),
which handles compile + OTA deploy.

## Status

`0.1` — MVP, no agent. `design.json` → ESPHome YAML + ASCII diagram.
Three boards / components in the library. See [`START.md`](START.md) for the
full roadmap.

## Quickstart

```sh
pip install -e .[dev]
python -m studio.generate examples/garage-motion.json
```

That prints the rendered YAML and the ASCII wiring block to stdout.
Pass `--out-yaml path.yaml` / `--out-ascii path.txt` to write to files.

## Layout

```
schema/                JSON Schema for design.json (the source of truth)
library/boards/        board manifests (pins, rails, framework)
library/components/    component manifests (electrical + ESPHome template)
studio/                python: model, library loader, generators
examples/              sample design.json files
tests/golden/          pinned outputs for regression tests
```

## Contributing

See [`CLAUDE.md`](CLAUDE.md) for working conventions.
