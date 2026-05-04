# esphome-studio web

Studio web UI. React 19 + Vite + TypeScript + Tailwind v4.

Pick an example from the left sidebar; the API renders it into YAML +
ASCII in the center pane. The right inspector lets you edit:

- **From the design view:** the board (dropdown of all library boards),
  fleet metadata (device_name + tags), requirements, warnings, plus
  the components list with **+ Add component** at the bottom and a ✕
  per instance.
- **From a component-instance view:** params (form generated from the
  library's `params_schema`) and connections (target kind + kind-specific
  controls — rail, gpio, design bus, expander pin).

Every edit pushes through a debounced (250ms) `POST /design/render` so
the YAML and ASCII update in real time.

**Adding a component** auto-wires the connections from the library
component's pin list: rails picked by voltage match (BME280 → 3V3,
PIR → 5V), I2C/SPI/UART/I2S pins linked to the first bus of the
matching type. If the design lacks a needed bus, the bus is
auto-prepended using the board's `default_buses` (so dropping a BME280
into an empty WeMos D1 Mini design also lays down `i2c0` on `D2/D1`).
Digital GPIO pins land as empty placeholders that the connection editor
shows as `(invalid: <unset>)` until you wire them.

Drag-and-drop wiring and the agent sidebar are later iterations.

Header buttons:
- **Connect device** opens a WebSerial dialog that runs esptool-js
  against a plugged-in ESP, reports the chip family + MAC, and lets
  you pick a matching board to bootstrap a fresh `design.json` from
  scratch. Chrome / Edge / Brave / Arc only — Firefox and Safari don't
  ship the WebSerial API.
- **Reset** reverts the current design to the loaded example.
- **Download JSON** saves the (possibly modified) `design.json` to disk.

## Dev

The UI talks to the studio API. Run both:

```sh
# Terminal 1 -- the API
cd .. && python -m studio.api

# Terminal 2 -- the UI
cd web && npm install && npm run dev
```

Open <http://localhost:5173>. Vite proxies `/api/*` to `http://127.0.0.1:8765`,
so the UI works without CORS or hardcoded hostnames in the source.

## Build

```sh
npm run build       # tsc + vite build into ./dist
npm run preview     # serve the built bundle on :4173
```

## Layout

```
src/
├── api/
│   └── client.ts            # typed fetch wrapper for /library, /design, /examples
├── types/
│   └── api.ts               # wire types matching studio/api/schemas.py
├── lib/
│   ├── debounce.ts          # useDebouncedValue
│   ├── design.ts            # immutable design helpers (params, connections,
│   │                        # board, fleet, requirements, warnings, add/remove)
│   ├── design.test.ts       # vitest unit tests covering the helpers
│   ├── bootstrap.ts         # normalizeChipFamily + candidateBoardsFor + bootstrapDesign
│   ├── bootstrap.test.ts    # vitest tests for the bootstrap helpers
│   └── usb-detect.ts        # esptool-js wrapper (dynamic-imported)
├── components/
│   ├── LeftSidebar.tsx      # tabs: Examples / Boards / Components, with search
│   ├── DesignPane.tsx       # tabs: ASCII / YAML / JSON; design metadata header
│   ├── Inspector.tsx        # routes between design / board / component / instance views
│   ├── ParamForm.tsx        # form generated from params_schema
│   ├── ConnectionForm.tsx   # per-connection editor (rail/gpio/bus/expander_pin)
│   └── UsbDetectDialog.tsx  # WebSerial chip-detect modal + bootstrap picker
├── App.tsx                  # state + data flow; three-pane grid
├── main.tsx
└── index.css                # Tailwind v4 + dark-mode base
```

## Tests

```sh
npm test            # vitest, runs once
npm run test:watch  # watch mode
```

Currently 49 tests across `lib/design.ts` (immutable patch helpers,
isDirty, readers, add/remove with auto-wiring + auto-bus) and
`lib/bootstrap.ts` (chip-family normalization, board candidate
matching, bootstrap-design shape). Component-level RTL tests are a
future iteration once we set up jsdom; the WebSerial flow gets
manual test only because there's no headless ESP.

## Editing model

- The current design is held entirely in browser state. There is no
  `/design/save` endpoint and no persistence; modifications stay local
  until you hit Download JSON.
- Every edit goes through `updateComponentParam` (in `lib/design.ts`),
  which never mutates -- it returns a new design with the targeted
  `params` key changed.
- A 250ms `useDebouncedValue` sits between `design` state and the
  `/design/render` POST so rapid typing in a numeric field doesn't
  flood the API.

## Param form coverage

`ParamForm` reads each entry of a library component's `params_schema`
and renders the appropriate control:

| schema | control |
|---|---|
| `enum: [...]` | `<select>` |
| `type: integer` / `number` | `<input type=number>` (with `min`/`max` if specified) |
| `type: boolean` | checkbox |
| anything else (default) | `<input type=text>` |
| `type: object` / `array` | read-only JSON view (structured editing not yet supported) |

Existing param values that aren't in the schema (e.g. ad-hoc keys a
designer added manually) render as read-only JSON labelled "not in
schema."
