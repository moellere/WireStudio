# esphome-studio web

Studio web UI. React 19 + Vite + TypeScript + Tailwind v4.

Pick an example from the left sidebar; the API renders it into YAML +
ASCII in the center pane. The right inspector lets you edit:

- **From the design view:** the board (dropdown of all library boards),
  fleet metadata (device_name + tags), requirements, warnings.
- **From a component-instance view:** params (form generated from the
  library's `params_schema`) and connections (target kind + kind-specific
  controls — rail, gpio, design bus, expander pin).

Every edit pushes through a debounced (250ms) `POST /design/render` so
the YAML and ASCII update in real time. Adding/removing components and
buses, drag-and-drop wiring, and the agent sidebar come in later
iterations.

Header buttons:
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
│   │                        # board, fleet, requirements, warnings)
│   └── design.test.ts       # vitest unit tests covering the helpers
├── components/
│   ├── LeftSidebar.tsx      # tabs: Examples / Boards / Components, with search
│   ├── DesignPane.tsx       # tabs: ASCII / YAML / JSON; design metadata header
│   ├── Inspector.tsx        # routes between design / board / component / instance views
│   ├── ParamForm.tsx        # form generated from params_schema
│   └── ConnectionForm.tsx   # per-connection editor (rail/gpio/bus/expander_pin)
├── App.tsx                  # state + data flow; three-pane grid
├── main.tsx
└── index.css                # Tailwind v4 + dark-mode base
```

## Tests

```sh
npm test            # vitest, runs once
npm run test:watch  # watch mode
```

Currently focused on `lib/design.ts` (20 tests covering the immutable
patch helpers, isDirty, and the array readers). Component-level RTL
tests are a future iteration once we set up jsdom.

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
