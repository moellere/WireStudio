import { useEffect, useState } from "react";

const STORAGE_KEY = "wirestudio:ui:layout";

/** Below this window width the sidebar starts as an icon rail and the inspector narrows. */
export const NARROW_PX = 1366;
/** At or above this width the agent docks as a fourth column instead of covering the inspector. */
export const DOCK_AGENT_PX = 1536;
/** The design pane never gets narrower than this (32rem). */
export const CENTRE_MIN_PX = 512;
export const RAIL_PX = 56;

export const BOUNDS = {
  sidebar: [224, 400],
  inspector: [320, 520],
  agent: [320, 640],
} as const;

export type Column = keyof typeof BOUNDS;

export interface Layout {
  sidebar: number;
  /** null until the user drags it: then the narrow-window default applies. */
  inspector: number | null;
  agent: number;
  /** null: follow the window width; true/false: the user chose. */
  sidebarCollapsed: boolean | null;
}

const DEFAULTS: Layout = { sidebar: 288, inspector: null, agent: 420, sidebarCollapsed: null };

export function clamp(column: Column, px: number): number {
  const [lo, hi] = BOUNDS[column];
  return Math.round(Math.min(hi, Math.max(lo, px)));
}

function readStored(): Partial<Layout> {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Partial<Layout>) : {};
  } catch {
    return {};
  }
}

export function readLayout(): Layout {
  const s = readStored();
  return {
    sidebar: typeof s.sidebar === "number" ? clamp("sidebar", s.sidebar) : DEFAULTS.sidebar,
    inspector: typeof s.inspector === "number" ? clamp("inspector", s.inspector) : DEFAULTS.inspector,
    agent: typeof s.agent === "number" ? clamp("agent", s.agent) : DEFAULTS.agent,
    sidebarCollapsed: typeof s.sidebarCollapsed === "boolean" ? s.sidebarCollapsed : null,
  };
}

function useWindowWidth(): number {
  const [width, setWidth] = useState(() => (typeof window === "undefined" ? 1440 : window.innerWidth));
  useEffect(() => {
    const onResize = () => setWidth(window.innerWidth);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  return width;
}

/** Column widths, remembered in this browser, with the narrow-window defaults applied. */
export function useWorkbenchLayout() {
  const [layout, setLayout] = useState<Layout>(readLayout);
  const windowWidth = useWindowWidth();

  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(layout));
    } catch {
      // In-memory state still works for this session.
    }
  }, [layout]);

  const narrow = windowWidth < NARROW_PX;
  return {
    layout,
    narrow,
    dockAgent: windowWidth >= DOCK_AGENT_PX,
    sidebarCollapsed: layout.sidebarCollapsed ?? narrow,
    inspectorWidth: layout.inspector ?? (narrow ? BOUNDS.inspector[0] : 384),
    resize: (column: Column, px: number) => setLayout((l) => ({ ...l, [column]: clamp(column, px) })),
    setSidebarCollapsed: (collapsed: boolean) => setLayout((l) => ({ ...l, sidebarCollapsed: collapsed })),
  };
}
