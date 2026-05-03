# esphome-studio

Agent-driven ESPHome device design tool. Describe a goal (or pick parts);
get an ESPHome YAML, an ASCII wiring diagram, and a BOM that compile
under upstream ESPHome.

Sister project to [`weirded/distributed-esphome`](https://github.com/weirded/distributed-esphome),
which handles compile + OTA deploy.

## Status

`0.1` — MVP pipeline. `design.json` (the source of truth) → ESPHome YAML +
ASCII diagram + BOM. No web UI, no agent, no API server yet — those are the
0.2-0.5 phases. See [`START.md`](START.md) for the roadmap and the rationale
behind each decision.

## Quickstart

```sh
pip install -e .[dev]
python -m studio.generate examples/garage-motion.json
```

Prints rendered YAML and the ASCII wiring block to stdout. To write to files:

```sh
python -m studio.generate examples/garage-motion.json \
    --out-yaml build/garage-motion.yaml \
    --out-ascii build/garage-motion.txt
```

The YAML is what you'd hand to `esphome compile <file>`; the ASCII is a
diff-friendly summary of the wiring, BOM, and power budget.

## Examples

| Example | Board | What it is |
|---|---|---|
| [`garage-motion.json`](examples/garage-motion.json) | ESP32-DevKitC-V4 | PIR + BME280 (temp/humidity/pressure) over I2C |
| [`awning-control.json`](examples/awning-control.json) | WeMos D1 Mini | Cover controller — limit switches + manual buttons via MCP23008 expander, dual-PWM motor drive |
| [`wasserpir.json`](examples/wasserpir.json) | WeMos D1 Mini | Single PIR with a scheduled nightly reboot |
| [`oled.json`](examples/oled.json) | WeMos D1 Mini | SSD1306 status display rendering time, date, IP |
| [`bluemotion.json`](examples/bluemotion.json) | WeMos D1 Mini | PIR + WS2812B NeoPixel; motion lights the LED |

Generated artifacts for each are pinned as goldens in
[`tests/golden/`](tests/golden/).

## Architecture

```
   design.json  ── single source of truth (JSON-Schema-validated)
        │
        ▼
  ┌─ studio.model      pydantic models mirroring the schema
  ├─ studio.library    loads boards/ + components/ YAML
  └─ studio.generate   pure functions:
       ├─ yaml_gen     design + library → ESPHome YAML
       └─ ascii_gen    design + library → wiring diagram + BOM
```

Generators are pure functions of `design.json` + the static library — no
artifact-to-document round-trips. Library files in `library/components/`
carry the electrical metadata ESPHome doesn't (pin roles, voltage ranges,
current draw, decoupling caps, pull-up requirements) plus a Jinja2 template
that renders the ESPHome YAML for that component.

## Library

Currently shipped:

**Boards** (`library/boards/`)
- `esp32-devkitc-v4` — ESP32 DevKitC V4 (ESP32-WROOM-32, 4MB flash)
- `wemos-d1-mini` — WeMos D1 Mini (ESP-12F module, ESP8266)

**Components** (`library/components/`)
- `bme280` — Bosch temperature/humidity/pressure sensor (I2C)
- `hc-sr501` — PIR motion sensor (used as a generic PIR)
- `ssd1306` — 128×64 OLED (I2C)
- `mcp23008` — 8-bit I2C GPIO expander
- `ws2812b` — addressable RGB LED (NeoPixel/neopixelbus)

The library is intentionally small. It will grow as we convert more
device configs from the corpus in `moellere/esphome`. See
[`START.md` § Library sourcing strategy](START.md#library-sourcing-strategy)
for the hybrid plan.

## Layout

```
schema/                   JSON Schema for design.json (source of truth)
library/boards/           board manifests (pinout, rails, framework)
library/components/       component manifests (electrical + ESPHome template)
studio/                   python: model, library loader, generators, CLI
examples/                 sample design.json files
tests/                    pytest suite + golden artifacts
START.md                  vision, decisions, phase plan
CLAUDE.md                 working conventions for both Claude and humans
```

## Tests

```sh
python -m pytest          # full suite
python -m ruff check .    # lint
```

Golden tests pin the generator output for every example. Regenerate goldens
with the CLI when output legitimately changes; commit the new files in the
same diff as the code change.

## Roadmap (compressed)

- **0.1** ✅ pipeline + 5 examples + library scaffolding
- **0.2** HTTP API (FastAPI) — same generators, exposed over JSON
- **0.3** Studio web UI v1 — board picker, component browser, live diagram
- **0.4** USB device bootstrap via WebSerial / esptool-js
- **0.5** Agent layer (Claude tool-using, in the UI sidebar)
- **0.6** CSP solver — pin/bus/budget assignment + ranked recommendations
- **0.7** distributed-esphome handoff — push device + YAML to ha-addon
- **0.8** Enclosure suggestions
- **Future** KiCad schematic + PCB layout

Full plan with decisions, schemas, and per-phase scope lives in
[`START.md`](START.md).

## Contributing

See [`CLAUDE.md`](CLAUDE.md) for working conventions (concise prose, no
emojis in code/commits, no premature abstraction, default-to-no-comments,
boundary-only validation).

## License

MIT. See [`LICENSE`](LICENSE).
