# Contributing to wirestudio

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

1. Installs the pinned ESPHome (currently `==2025.12.7`).
2. For every `examples/*.json`, renders YAML through
   `wirestudio.generate.yaml_gen` and runs `esphome config <file>` against
   it.
3. Fails the merge if any example doesn't validate.

This is the canonical proof that the studio's output is real, not
plausible-looking text. **Do not merge a change that breaks this
gate.** It's the gate the project can be judged by from the outside.

### Running the gate locally

```sh
pip install -e .[dev]
pip install 'esphome==2025.12.7'
python scripts/check_examples.py            # all examples
python scripts/check_examples.py garage-motion oled    # just these two
python scripts/check_examples.py --keep     # leave generated YAML on disk
```

On Debian/Ubuntu hosts the system `python3-setuptools` ships patched in a
way that breaks ESPHome's pinned `paho-mqtt` source build. If `pip install
esphome` fails on the `paho-mqtt` wheel, drop into a fresh venv first:
`python -m venv .venv && source .venv/bin/activate`. The CI workflow uses
`actions/setup-python@v5`, which sidesteps this.

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
6. The `--strict` coverage gate (`python scripts/coverage_matrix.py
   --strict`, also wired into CI) refuses the merge if a new library
   entry lands without an example unless you explicitly add it to
   `scripts/coverage_baseline.yaml`. When you close a gap by adding
   an example, also remove the id from the baseline — the gate fails
   on stale entries too.

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
  `_pins_for` helper in `wirestudio/generate/yaml_gen.py` is the right
  place to extend.
- **Stub secrets rejected.** `esphome config` validates the api
  encryption key as base64. The script already writes a 32-byte
  zero-base64 stub; if a new component introduces a new `!secret`
  reference, extend `_stub_value` in `scripts/check_examples.py`.

### Pre-push hook (recommended)

Run the same gate before any push leaves your machine. One-time
setup:

```sh
pip install pre-commit
pre-commit install --hook-type pre-push
```

After that, `git push` will run
`python scripts/check_examples.py` automatically and abort the push
if the gate fails. The hook also runs `ruff` at commit time. Skip a
single push with `git push --no-verify` when iterating on a WIP
feature branch.

The pre-commit config lives at `.pre-commit-config.yaml`. Same
`esphome==2025.12.7` install applies; same Debian-host venv
caveat above applies if the install trips on `paho-mqtt`.

### Bumping the pinned ESPHome

The pin is in **three** places: `.github/workflows/esphome-config.yml`,
`.github/workflows/esphome-compile.yml` (nightly compile smoke; see
below), and `README.md` (the version we advertise). Bump all three
in the same diff. The bump PR's burden of proof is "the gate passes
against the new version" — not "the new version is fashionable."

The [`esphome-matrix`](.github/workflows/esphome-matrix.yml) workflow
(scheduled + manual) runs the example gate across the pin plus the
latest stables, so you can see a candidate version go green across the
board *before* bumping. When it does, bump the pin (and add the new
version to the matrix list); when it's red, the failing examples show
what upstream changed.

### Nightly compile smoke

`.github/workflows/esphome-compile.yml` runs `esphome compile`
(not just `config`) against one representative example
(`garage-motion` by default) every night at 11:00 UTC, plus on
manual dispatch. It catches things `esphome config` can't:

- a new PlatformIO toolchain release breaks the build
- a new ESPHome release accepts our YAML but its codegen breaks
- a `python:3.11-slim` security update knocks out a build dep

Compile is slow (cold-cache: ~10min; warm: ~3min) and the failures
are upstream churn rather than contributor churn, so it's
intentionally gated to nightly + manual rather than running on
every PR. To trigger an ad-hoc compile against a specific example,
use the **Run workflow** button on the workflow's Actions tab and
pass the example stem as input.

To run the same compile-smoke locally:

```sh
python scripts/check_examples.py --compile garage-motion
```

(First-time toolchain pull will take several minutes.)

## The schematic gate

`.github/workflows/kicad-schematic.yml` runs `scripts/check_schematics.py`
against the pinned upstream KiCad symbol libraries. For every
`examples/*.json` it renders the SKiDL script, executes it against the
real symbol set, and emits a netlist — failing the PR if any
component/board `kicad:` block references a symbol that doesn't exist or
maps a connected pin role to a pin the symbol lacks. This is the
**Verified** bar for the schematic: not "the emitted Python parses" but
"it builds a netlist against KiCad's own symbols."

`tests/test_kicad.py` covers the emitter's structure (well-formed
Python, expected nets, pin-map application) without needing KiCad;
`tests/test_schematics_gate.py` mirrors the netlist gate and skips
unless `KICAD8_SYMBOL_DIR` points at a `kicad-symbols` checkout.

### Running the schematic gate locally

```sh
pip install --no-deps skidl graphviz simp_sexp
git clone --depth 1 --branch 8.0.0 \
    https://gitlab.com/kicad/libraries/kicad-symbols.git
export KICAD8_SYMBOL_DIR=$PWD/kicad-symbols
python scripts/check_schematics.py            # all examples
python scripts/check_schematics.py garage-motion
```

### `kicad:` mapping rules

When adding or editing a component/board, its `kicad:` block must
netlist:

- **Real symbol where one exists.** Map `symbol_lib` / `symbol` to the
  actual upstream KiCad symbol, and give `pin_map` an entry for every
  role whose name differs from the symbol's pin (e.g. `VCC: VDD`,
  `GND: VSS`, `CS: "~{CS}"`). Run the gate; SKiDL names the offending
  pin if you miss one.
- **Generic header otherwise.** KiCad ships no symbol for most sensor /
  module breakouts. Map those to `Connector_Generic:Conn_01x0N` (N = pin
  count) with `value:` set to the real part name. The generator binds
  generic-connector pins positionally by the order of `electrical.pins`,
  so no `pin_map` is needed — but every connected role must be declared
  in `electrical.pins`.
- **Boards** map to the onboard module/MCU symbol (e.g. an ESP32 DevKitC
  to `RF_Module:ESP32-WROOM-32`); board pins float in the schematic, so
  only the symbol needs to resolve.

When you bump `KICAD_SYMBOLS_REF` in the workflow, expect symbol renames
across the major version and re-run the gate.

## The enclosure gate

`.github/workflows/enclosure-render.yml` runs `scripts/check_enclosures.py`,
which renders every enclosure-capable board's `.scad` through real
OpenSCAD and fails the PR unless it produces a non-empty, manifold
(closed, non-self-intersecting) solid. This is the **Verified** bar for
enclosures: not "the `.scad` parses" but "it renders to a printable
solid." The geometry is board-driven (from the board's `enclosure:`
block), so the gate walks boards, not examples.

```sh
sudo apt-get install -y openscad
python scripts/check_enclosures.py            # all enclosure boards
python scripts/check_enclosures.py wemos-d1-mini
```

When you add an `enclosure:` block to a board, run the gate — OpenSCAD
will reject self-intersecting standoffs or port cutouts that breach a
wall. `tests/test_enclosure_gate.py` mirrors it and skips when
`openscad` is absent.

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
    python -m wirestudio.generate "$f" \
        --out-yaml "tests/golden/${name}.yaml" \
        --out-ascii "tests/golden/${name}.txt"
done
```

## Quick checklist before opening a PR

- [ ] `python -m pytest` passes.
- [ ] `python -m ruff check .` passes.
- [ ] `python scripts/check_examples.py` passes against the pinned
      ESPHome (or the pre-push hook ran on `git push`).
- [ ] `python scripts/check_schematics.py` passes against the pinned
      KiCad symbols (if you touched a `kicad:` block or added a part).
- [ ] `python scripts/check_enclosures.py` passes (if you touched a
      board's `enclosure:` block).
- [ ] If you added or changed a library entry, an example uses it.
- [ ] If a golden changed, the regenerated golden is in the same diff.
- [ ] If you bumped the ESPHome pin, all three pin sites (config
      workflow, compile workflow, README) moved together.
