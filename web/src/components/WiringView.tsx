import { useMemo, useState } from "react";
import type { Design } from "../types/api";

/**
 * Read-only logical wiring diagram. Same data the ASCII view prints,
 * drawn as an SVG net graph: board pins/rails on the left, buses in a
 * middle lane, components on the right. Hovering a row or edge
 * highlights its net. Layout is computed from row indexes -- no
 * physical placement is implied.
 */

interface Conn {
  component_id: string;
  pin_role: string;
  target: Record<string, unknown> | null;
}

interface Comp {
  id: string;
  library_id: string;
  label?: string;
}

interface Bus {
  id: string;
  type: string;
  pins: Array<[string, string]>;
}

const ROW_H = 22;
const HEAD_H = 30;
const PAD_Y = 6;
const CARD_W = 220;
const BOARD_X = 10;
const BUS_X = 330;
const COMP_X = 640;
const TOP = 14;
const CARD_GAP = 18;

const RAIL_ORDER: Record<string, number> = { "5V": 0, VIN: 0, "3V3": 1, GND: 2 };

function railClass(name: string): string {
  if (name === "GND") return "stroke-ink-faint";
  if (name.startsWith("3")) return "stroke-amber-400";
  return "stroke-rose-400";
}

function busClass(type: string): string {
  if (type === "i2c") return "stroke-emerald-400";
  if (type === "spi") return "stroke-agent-400";
  return "stroke-accent-400";
}

function trunc(s: string, max: number): string {
  return s.length > max ? s.slice(0, max - 1) + "…" : s;
}

function gpioNum(pin: string): number {
  const m = pin.match(/\d+/);
  return m ? Number(m[0]) : 999;
}

function targetLabel(t: Record<string, unknown> | null): string {
  if (!t || !t.kind) return "unassigned";
  const kind = String(t.kind);
  if (kind === "gpio") return String(t.pin);
  if (kind === "rail") return String(t.rail);
  if (kind === "bus") return String(t.bus_id);
  if (kind === "component") return String(t.component_id);
  if (kind === "expander_pin") return `${t.expander_id}.${t.number}`;
  return kind;
}

/** Net key shared by every row/edge belonging to the same electrical net. */
function netKey(t: Record<string, unknown> | null): string | null {
  if (!t || !t.kind) return null;
  const kind = String(t.kind);
  if (kind === "gpio") return `gpio:${t.pin}`;
  if (kind === "rail") return `rail:${t.rail}`;
  if (kind === "bus") return `bus:${t.bus_id}`;
  if (kind === "component") return `comp:${t.component_id}`;
  if (kind === "expander_pin") return `comp:${t.expander_id}`;
  return null;
}

function edgePath(x1: number, y1: number, x2: number, y2: number): string {
  if (x1 === x2) {
    const bow = x1 - 40;
    return `M ${x1} ${y1} C ${bow} ${y1}, ${bow} ${y2}, ${x2} ${y2}`;
  }
  const mx = (x1 + x2) / 2;
  return `M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`;
}

export function WiringView({ design }: { design: Design }) {
  const [hover, setHover] = useState<string | null>(null);

  const model = useMemo(() => buildModel(design), [design]);

  const dim = (key: string | null) =>
    hover !== null && key !== hover ? "opacity-20" : "";

  return (
    <div className="overflow-auto">
      <div className="mb-3 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-ink-faint">
        <span className="flex items-center gap-1.5"><i className="h-0.5 w-4 rounded bg-rose-400" /> power</span>
        <span className="flex items-center gap-1.5"><i className="h-0.5 w-4 rounded bg-amber-400" /> 3V3</span>
        <span className="flex items-center gap-1.5"><i className="h-0.5 w-4 rounded bg-ink-faint" /> ground</span>
        <span className="flex items-center gap-1.5"><i className="h-0.5 w-4 rounded bg-emerald-400" /> i2c</span>
        <span className="flex items-center gap-1.5"><i className="h-0.5 w-4 rounded bg-agent-400" /> spi</span>
        <span className="flex items-center gap-1.5"><i className="h-0.5 w-4 rounded bg-accent-400" /> gpio / data</span>
      </div>

      <svg
        viewBox={`0 0 ${COMP_X + CARD_W + 10} ${model.height}`}
        className="min-w-[820px] font-sans"
        style={{ width: "100%" }}
        onMouseLeave={() => setHover(null)}
      >
        {/* edges under nodes */}
        {model.edges.map((e, i) => (
          <path
            key={i}
            d={edgePath(e.x1, e.y1, e.x2, e.y2)}
            className={`fill-none ${e.cls} ${e.dashed ? "" : ""} ${dim(e.net)} transition-opacity`}
            strokeWidth={e.net === hover ? 2.2 : 1.4}
            strokeDasharray={e.dashed ? "4 3" : undefined}
            strokeLinecap="round"
            onMouseEnter={() => setHover(e.net)}
          />
        ))}

        {model.cards.map((card) => (
          <g key={card.key}>
            <rect
              x={card.x}
              y={card.y}
              width={CARD_W}
              height={card.h}
              rx={8}
              className={`fill-surface-1 stroke-line ${dim(card.net)} transition-opacity`}
            />
            <text
              x={card.x + 10}
              y={card.y + 19}
              className={`fill-ink text-[12px] font-semibold ${dim(card.net)}`}
              onMouseEnter={card.net ? () => setHover(card.net) : undefined}
            >
              {trunc(card.title, card.subtitle ? 17 : 28)}
            </text>
            {card.subtitle && (
              <text
                x={card.x + CARD_W - 10}
                y={card.y + 19}
                textAnchor="end"
                className={`fill-ink-faint font-mono text-[10px] ${dim(card.net)}`}
              >
                {trunc(card.subtitle, 16)}
              </text>
            )}
            {card.rows.map((r, i) => {
              const y = card.y + HEAD_H + PAD_Y + i * ROW_H + ROW_H / 2;
              return (
                <g
                  key={i}
                  onMouseEnter={() => setHover(r.net)}
                  className={`${dim(r.net)} transition-opacity`}
                >
                  <rect
                    x={card.x + 4}
                    y={y - ROW_H / 2 + 1}
                    width={CARD_W - 8}
                    height={ROW_H - 2}
                    rx={4}
                    className={r.net === hover ? "fill-accent-500/10" : "fill-transparent"}
                  />
                  <circle cx={r.dotLeft ? card.x : card.x + CARD_W} cy={y} r={3} className={`${r.dotCls} stroke-none`} />
                  <text x={card.x + 12} y={y + 4} className="fill-ink font-mono text-[11px]">
                    {r.label}
                  </text>
                  <text
                    x={card.x + CARD_W - 12}
                    y={y + 4}
                    textAnchor="end"
                    className={`font-mono text-[10px] ${r.value === "unassigned" ? "fill-rose-400" : "fill-ink-faint"}`}
                  >
                    {r.value}
                  </text>
                </g>
              );
            })}
          </g>
        ))}
      </svg>
    </div>
  );
}

interface Row {
  label: string;
  value: string;
  net: string | null;
  dotLeft: boolean;
  dotCls: string;
}

interface Card {
  key: string;
  title: string;
  subtitle?: string;
  x: number;
  y: number;
  h: number;
  net: string | null;
  rows: Row[];
}

interface Edge {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  cls: string;
  net: string;
  dashed?: boolean;
}

function buildModel(design: Design) {
  const comps: Comp[] = Array.isArray(design.components)
    ? (design.components as Comp[])
    : [];
  const conns: Conn[] = Array.isArray(design.connections)
    ? (design.connections as unknown as Conn[])
    : [];
  const busesRaw = Array.isArray(design.buses) ? (design.buses as Array<Record<string, unknown>>) : [];
  const buses: Bus[] = busesRaw.map((b) => ({
    id: String(b.id ?? ""),
    type: String(b.type ?? ""),
    pins: Object.entries(b).filter(
      ([k, v]) => !["id", "type", "frequency_hz"].includes(k) && typeof v === "string" && /^(GPIO|D|A)\d/i.test(String(v)),
    ) as Array<[string, string]>,
  }));

  const boardId = String((design.board as Record<string, unknown> | undefined)?.library_id ?? "board");

  // ⚡ Bolt: Use single-pass loops to build Sets, avoiding intermediate allocations from .filter().map()
  const railSet = new Set<string>();
  const gpioSet = new Set<string>();
  for (const c of conns) {
    if (c.target?.kind === "rail") {
      railSet.add(String(c.target.rail));
    } else if (c.target?.kind === "gpio") {
      gpioSet.add(String(c.target.pin));
    }
  }
  for (const b of buses) {
    for (const [, pin] of b.pins) {
      gpioSet.add(pin);
    }
  }

  const railsUsed = Array.from(railSet).sort(
    (a, b) => (RAIL_ORDER[a] ?? 9) - (RAIL_ORDER[b] ?? 9) || a.localeCompare(b),
  );
  const gpiosUsed = Array.from(gpioSet).sort(
    (a, b) => gpioNum(a) - gpioNum(b),
  );

  const cards: Card[] = [];
  const edges: Edge[] = [];

  const boardRows: Row[] = [
    ...railsUsed.map((r) => ({
      label: r,
      value: "rail",
      net: `rail:${r}`,
      dotLeft: false,
      dotCls: r === "GND" ? "fill-ink-faint" : r.startsWith("3") ? "fill-amber-400" : "fill-rose-400",
    })),
    ...gpiosUsed.map((p) => ({
      label: p,
      value: "",
      net: `gpio:${p}`,
      dotLeft: false,
      dotCls: "fill-accent-400",
    })),
  ];
  const boardCard: Card = {
    key: "board",
    title: boardId,
    subtitle: String((design.board as Record<string, unknown> | undefined)?.mcu ?? ""),
    x: BOARD_X,
    y: TOP,
    h: HEAD_H + PAD_Y * 2 + boardRows.length * ROW_H,
    net: null,
    rows: boardRows,
  };
  cards.push(boardCard);

  const boardRowY = new Map<string, number>();
  boardRows.forEach((r, i) => {
    boardRowY.set(r.net!, TOP + HEAD_H + PAD_Y + i * ROW_H + ROW_H / 2);
  });

  let busY = TOP;
  const busRowY = new Map<string, Map<string, number>>();
  for (const b of buses) {
    const rows: Row[] = b.pins.map(([k, pin]) => ({
      label: k.toUpperCase(),
      value: pin,
      net: `bus:${b.id}`,
      dotLeft: true,
      dotCls: b.type === "i2c" ? "fill-emerald-400" : b.type === "spi" ? "fill-agent-400" : "fill-accent-400",
    }));
    const h = HEAD_H + PAD_Y * 2 + rows.length * ROW_H;
    cards.push({
      key: `bus:${b.id}`,
      title: b.id,
      subtitle: b.type,
      x: BUS_X,
      y: busY,
      h,
      net: `bus:${b.id}`,
      rows,
    });
    const rowMap = new Map<string, number>();
    b.pins.forEach(([k, pin], i) => {
      const y = busY + HEAD_H + PAD_Y + i * ROW_H + ROW_H / 2;
      rowMap.set(k.toLowerCase(), y);
      const by = boardRowY.get(`gpio:${pin}`);
      if (by !== undefined) {
        edges.push({
          x1: BOARD_X + CARD_W,
          y1: by,
          x2: BUS_X,
          y2: y,
          cls: busClass(b.type),
          net: `bus:${b.id}`,
        });
      }
    });
    busRowY.set(b.id, rowMap);
    busY += h + CARD_GAP;
  }

  const connsByComp = new Map<string, Conn[]>();
  for (const c of conns) {
    const list = connsByComp.get(c.component_id) ?? [];
    list.push(c);
    connsByComp.set(c.component_id, list);
  }

  let compY = TOP;
  const compHeaderY = new Map<string, number>();
  const compRowY = new Map<string, Map<string, number>>();
  for (const comp of comps) {
    const compConns = connsByComp.get(comp.id) ?? [];
    const rows: Row[] = compConns.map((c) => ({
      label: c.pin_role,
      value: targetLabel(c.target),
      net: netKey(c.target),
      dotLeft: true,
      dotCls:
        c.target?.kind === "rail"
          ? String(c.target.rail) === "GND"
            ? "fill-ink-faint"
            : String(c.target.rail).startsWith("3")
              ? "fill-amber-400"
              : "fill-rose-400"
          : c.target?.kind === "bus"
            ? busClass(buses.find((b) => b.id === c.target!.bus_id)?.type ?? "")
                .replace("stroke-", "fill-")
            : "fill-accent-400",
    }));
    const h = HEAD_H + PAD_Y * 2 + rows.length * ROW_H;
    cards.push({
      key: `comp:${comp.id}`,
      title: comp.label || comp.id,
      subtitle: comp.library_id,
      x: COMP_X,
      y: compY,
      h,
      net: `comp:${comp.id}`,
      rows,
    });
    compHeaderY.set(comp.id, compY + HEAD_H / 2 + 4);
    const rowMap = new Map<string, number>();
    compConns.forEach((c, i) => {
      rowMap.set(c.pin_role, compY + HEAD_H + PAD_Y + i * ROW_H + ROW_H / 2);
    });
    compRowY.set(comp.id, rowMap);
    compY += h + CARD_GAP;
  }

  for (const comp of comps) {
    for (const c of connsByComp.get(comp.id) ?? []) {
      const y1 = compRowY.get(comp.id)?.get(c.pin_role);
      if (y1 === undefined || !c.target?.kind) continue;
      const kind = String(c.target.kind);
      const net = netKey(c.target)!;
      if (kind === "rail" || kind === "gpio") {
        const key = kind === "rail" ? `rail:${c.target.rail}` : `gpio:${c.target.pin}`;
        const y2 = boardRowY.get(key);
        if (y2 !== undefined) {
          edges.push({
            x1: COMP_X,
            y1,
            x2: BOARD_X + CARD_W,
            y2,
            cls: kind === "rail" ? railClass(String(c.target.rail)) : "stroke-accent-400",
            net,
          });
        }
      } else if (kind === "bus") {
        const rowMap = busRowY.get(String(c.target.bus_id));
        const y2 = rowMap?.get(c.pin_role.toLowerCase()) ?? averageY(rowMap);
        if (y2 !== undefined) {
          edges.push({
            x1: COMP_X,
            y1,
            x2: BUS_X + CARD_W,
            y2,
            cls: busClass(buses.find((b) => b.id === c.target!.bus_id)?.type ?? ""),
            net,
          });
        }
      } else if (kind === "component" || kind === "expander_pin") {
        const targetId = String(kind === "component" ? c.target.component_id : c.target.expander_id);
        const y2 = compHeaderY.get(targetId);
        if (y2 !== undefined) {
          edges.push({
            x1: COMP_X,
            y1,
            x2: COMP_X,
            y2,
            cls: "stroke-accent-400",
            net,
            dashed: true,
          });
        }
      }
    }
  }

  const height = Math.max(
    boardCard.y + boardCard.h,
    busY,
    compY,
  ) + 14;

  return { cards, edges, height };
}

function averageY(rowMap: Map<string, number> | undefined): number | undefined {
  if (!rowMap || rowMap.size === 0) return undefined;
  let sum = 0;
  for (const y of rowMap.values()) sum += y;
  return sum / rowMap.size;
}
