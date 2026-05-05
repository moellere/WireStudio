# wirestudio web

Studio web UI. React 19 + Vite + TypeScript + Tailwind v4.

Pick an example from the left sidebar; the API renders it into YAML +
ASCII in the center pane. The right inspector lets you edit:

- **From the design view:** the board (dropdown of all library boards),
  fleet metadata (device_name + tags), requirements, warnings, plus
  the components list with **+ Add component** at the bottom and a ✕
  per instance. A **Compatibility** section lists every pin that's
  in violation of its chip-level restrictions (boot strap pins driven
  as outputs, input-only pins used as outputs, pins shared with the
  USB serial console, A0 voltage caps, no-i2c pins on an I2C bus).
  Live: re-runs on every render.
- **From a component-instance view:** params (form generated from the
  library's `params_schema`), connections (target kind + kind-specific
  controls — rail, gpio, design bus, expander pin), and any
  compatibility warnings filtered to that instance's pins.

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
- **Solve pins** runs the pin-assignment solver against the current
  design: every unbound connection (gpio with empty pin, bus with empty
  bus_id, expander_pin with empty expander_id) gets filled in using the
  board's GPIO capability map, the design's existing buses, and any
  io_expander components. A banner shows the assignments made plus any
  conflicts (two connections targeting the same GPIO) and current-budget
  warnings. Doesn't reassign already-bound pins -- those are the user's
  call.
- **Agent** opens the Claude tool-using sidebar. Type natural-language
  edits ("add a BME280 over I2C", "swap the PIR to GPIO5", "validate",
  "what would I need for an outdoor weather station?") and the agent
  calls a constrained tool surface; design changes flow back into the
  live YAML/ASCII immediately. **Streamed**: text and tool calls land
  live as the agent works, with each pending tool call showing
  `running…` then `ok` / `failed` status. The `recommend` tool ranks
  library components against capability queries before suggesting
  anything. Requires `ANTHROPIC_API_KEY` set on the API server.
  Conversation history is stored server-side in `sessions/<id>.jsonl`.
- **Connect device** opens a WebSerial dialog that runs esptool-js
  against a plugged-in ESP, reports the chip family + MAC, and lets
  you pick a matching board to bootstrap a fresh `design.json` from
  scratch. Chrome / Edge / Brave / Arc only — Firefox and Safari don't
  ship the WebSerial API.
- **Reset** reverts the current design to the loaded example
  (this also reverts any edits the agent made — its changes count
  as part of the working copy).
- **Download JSON** saves the (possibly modified) `design.json` to disk.
- **Push to fleet** opens a dialog that POSTs the rendered YAML to a
  configured distributed-esphome ha-addon (`FLEET_URL` + `FLEET_TOKEN`
  on the API server). The dialog shows live status (configured /
  unauthorized / unreachable), the device-name slug that will land on
  the fleet, and an opt-in "compile after upload" checkbox. When a
  compile is enqueued the dialog tails the build log (1.5s polling
  over `/fleet/jobs/{run_id}/log`) into a scrolling viewer until the
  job finishes.
- **Add by function** opens a two-pane picker. The left column lists
  every capability advertised by the library (sorted by how many
  components support it) plus a free-text input; the right column
  ranks library components for the active query (same recommender
  the agent uses) and offers a one-click **Add** button per result.
  The top match is badged "top pick" but the user is free to pick a
  different one — handy when you have a specific part on hand and
  want to use *that* sensor rather than the library default.

## Dev

The UI talks to the studio API. Run both:

```sh
# Terminal 1 -- the API
cd .. && python -m wirestudio.api

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
│   └── api.ts               # wire types matching wirestudio/api/schemas.py
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
│   ├── UsbDetectDialog.tsx  # WebSerial chip-detect modal + bootstrap picker
│   ├── AgentSidebar.tsx     # Claude agent chat drawer; replaces the working design on each turn
│   └── SolveResultBanner.tsx  # transient banner surfacing assignments + warnings from /design/solve_pins
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
