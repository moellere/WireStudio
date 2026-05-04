# esphome-studio web

Studio web UI v1. React 19 + Vite + TypeScript + Tailwind v4. Read-only
in this PR — picks an example, fetches `/design/render`, shows YAML +
ASCII + parsed metadata in a three-pane layout. Editing forms, drag-and-
drop, and the agent sidebar come in later 0.3+ iterations.

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
│   └── client.ts         # typed fetch wrapper for /library, /design, /examples
├── types/
│   └── api.ts            # wire types matching studio/api/schemas.py
├── components/
│   ├── LeftSidebar.tsx   # tabs: Examples / Boards / Components, with search
│   ├── DesignPane.tsx    # tabs: ASCII / YAML / JSON; design metadata header
│   └── Inspector.tsx     # design-/board-/component-detail read-only panels
├── App.tsx               # state + data flow; three-pane grid
├── main.tsx
└── index.css             # Tailwind v4 + dark-mode base
```
