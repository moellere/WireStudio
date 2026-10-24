import type { DrcSummary } from "../types/api";

function fmtPos(p: { x: number | null; y: number | null } | null): string {
  return p && p.x !== null && p.y !== null ? ` @ (${p.x.toFixed(2)}, ${p.y.toFixed(2)}) mm` : "";
}

/** KiCad's DRC of the routed board: the airwire count first, then each
 *  violation type with its items; waived types are listed but collapsed. */
export function RouteDrcReport({ drc }: { drc: DrcSummary | { error: string } | null | undefined }) {
  if (drc === undefined) return null;
  if (drc === null) {
    return <div className="text-xs text-ink-faint">DRC not run: kicad-cli is not on the server.</div>;
  }
  if ("error" in drc) {
    return <div className="text-xs text-rose-300">DRC failed to run: {drc.error}</div>;
  }
  const verdict = drc.ok
    ? "bg-emerald-500/10 text-emerald-200 ring-emerald-500/30"
    : "bg-amber-500/10 text-amber-200 ring-amber-500/30";
  return (
    <div className="space-y-1.5 text-xs">
      <div className={`rounded-md px-2 py-1.5 ring-1 ${verdict}`}>
        DRC: {drc.unconnected} unconnected · {drc.errors} error{drc.errors === 1 ? "" : "s"} ·{" "}
        {drc.warnings} warning{drc.warnings === 1 ? "" : "s"}
        {drc.waived > 0 && <span className="text-ink-faint"> · {drc.waived} waived</span>}
      </div>
      {drc.groups.map((g) => (
        <details key={g.type} open={!g.waived && g.severity === "error"} className="rounded-md bg-surface-2/40 px-2 py-1">
          <summary className="cursor-pointer text-ink-dim">
            <span className="font-mono">{g.type}</span> × {g.count}{" "}
            <span className={g.waived ? "text-ink-faint" : g.severity === "error" ? "text-rose-300" : "text-amber-300"}>
              {g.waived ? "waived" : g.severity}
            </span>
            {g.reason && <span className="text-ink-faint"> — {g.reason}</span>}
          </summary>
          <ul className="mt-1 space-y-1 pl-3">
            {g.violations.slice(0, 20).map((v, i) => (
              <li key={i} className="text-ink-faint">
                {v.description}
                {v.items.map((it, j) => (
                  <div key={j} className="pl-2 font-mono text-[11px]">{it.description}{fmtPos(it.pos)}</div>
                ))}
              </li>
            ))}
            {g.violations.length > 20 && <li className="text-ink-ghost">…and {g.violations.length - 20} more</li>}
          </ul>
        </details>
      ))}
    </div>
  );
}
