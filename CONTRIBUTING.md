# Contributing to esphome-studio

This file is the working bar for changes that touch the studio's
output. Conventions for prose, comments, and architecture live in
[`CLAUDE.md`](CLAUDE.md); this file is the *substantive* bar — what
"working" means for the things the studio produces.

## Priorities

Roughly ordered by how much they decide whether the studio is useful
at all:

1. **YAML production correctness.** Whatever the studio emits has to
   round-trip through upstream `esphome config`. This is the
   non-negotiable bar.
2. **Wiring schema correctness.** Generated schematics (SKiDL → KiCad)
   open in KiCad and the nets are right. Pin solver picks legal pins.
   Compatibility checker catches the issues it claims to (boot strap,
   ADC2/WiFi, voltage, locked-pin).
3. **Enclosure suggestions.** Parametric `.scad` printable + search
   relay returns relevant community models. Lower bar than (1) and (2)
   — a wrong enclosure is a 3D-print iteration, not a bricked device.
4. **PCB layout.** Deferred to 1.0+. Don't add surface area here until
   the three above are tight.

## The YAML gate

Every PR runs `.github/workflows/esphome-config.yml`, which:

1. Installs the pinned ESPHome (currently `~=2025.5`).
2. For every `examples/*.json`, renders YAML through
   `studio.generate.yaml_gen` and runs `esphome config <file>` against
   it.
3. Fails the merge if any example doesn't validate.

This is the canonical proof that the studio's output is real, not
plausible-looking text. **Do not merge a change that breaks this
gate.** It's the gate the project can be judged by from the outside.

### Running the gate locally

```sh
pip install -e .[dev]
pip install 'esphome~=2025.5'
python scripts/check_examples.py            # all examples
python scripts/check_examples.py garage-motion oled    # just these two
python scripts/check_examples.py --keep     # leave generated YAML on disk
```

### Adding a new component or board

1. Add the `library/components/<id>.yaml` (or `library/boards/<id>.yaml`)
   entry.
2. Add or update at least one `examples/*.json` that exercises it.
3. Add the matching golden under `tests/golden/`.
4. Run `python scripts/check_examples.py` locally. Fix anything that
   fails before opening a PR.
5. The CI gate is the bar — your component is "supported" only when
   an example using it round-trips through `esphome config`. If the
   component doesn't have an example yet, it isn't supported, even
   if the YAML template "looks right."

### When the gate fails

Read the tail output the script prints. Common causes:

- **Schema rejection.** ESPHome added/renamed a key between releases.
  Either fix the template to emit the new shape, or pin to the
  prior minor and document the constraint.
- **Missing required key.** ESPHome enforces required keys per
  platform (e.g., `address` on `bme280_i2c`). Surface it in the
  component's `params_schema` so the design-time form catches it.
- **Wrong pin format.** ESPHome accepts `GPIO13` or `13` for ESP32
  but the expander-pin block has different requirements. The
  `_pins_for` helper in `studio/generate/yaml_gen.py` is the right
  place to extend.
- **Stub secrets rejected.** `esphome config` validates the api
  encryption key as base64. The script already writes a 32-byte
  zero-base64 stub; if a new component introduces a new `!secret`
  reference, extend `_stub_value` in `scripts/check_examples.py`.

### Bumping the pinned ESPHome

The pin is in two places: `.github/workflows/esphome-config.yml`
(the version we test against) and `README.md` (the version we
advertise). Bump both in the same diff. The bump PR's burden of
proof is "the gate passes against the new version" — not "the new
version is fashionable."

## The schematic gate (lighter)

`tests/test_kicad.py` runs the SKiDL emitter against bundled examples
and checks the output is well-formed Python plus the expected nets.
It does **not** run KiCad to validate. The honest bar for "schematic
works" is: open the generated `.kicad_sch` in KiCad and verify the
nets visually. Add one such check per new component class.

## Tests

```sh
python -m pytest          # ~297 cases, ~10s
python -m ruff check .    # lint
cd web && npx vitest run  # ~125 cases (vitest + jsdom)
```

Goldens in `tests/golden/` are pinned. When the generator output
legitimately changes, regenerate them in the same PR as the code
change:

```sh
for f in examples/*.json; do
    name=$(basename "$f" .json)
    python -m studio.generate "$f" \
        --out-yaml "tests/golden/${name}.yaml" \
        --out-ascii "tests/golden/${name}.txt"
done
```

## Quick checklist before opening a PR

- [ ] `python -m pytest` passes.
- [ ] `python -m ruff check .` passes.
- [ ] `python scripts/check_examples.py` passes against the pinned
      ESPHome.
- [ ] If you added or changed a library entry, an example uses it.
- [ ] If a golden changed, the regenerated golden is in the same diff.
- [ ] If you bumped the ESPHome pin, README's "tested against" line
      moved with it.
