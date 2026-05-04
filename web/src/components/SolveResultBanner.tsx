import type { PinAssignment, SolverWarning } from "../types/api";

interface Props {
  assigned: PinAssignment[];
  unresolved: SolverWarning[];
  warnings: SolverWarning[];
  onDismiss: () => void;
}

export function SolveResultBanner({ assigned, unresolved, warnings, onDismiss }: Props) {
  const hasIssues = unresolved.length > 0 || warnings.length > 0;
  return (
    <div
      className={`flex items-start gap-3 border-b px-4 py-2 text-xs ${
        hasIssues
          ? "border-amber-500/40 bg-amber-500/10 text-amber-100"
          : "border-emerald-500/40 bg-emerald-500/10 text-emerald-100"
      }`}
    >
      <div className="flex-1 space-y-1">
        <div className="font-semibold">
          Solver assigned {assigned.length} pin{assigned.length === 1 ? "" : "s"}
          {hasIssues && ` · ${unresolved.length + warnings.length} issue${unresolved.length + warnings.length === 1 ? "" : "s"}`}
        </div>
        {assigned.length > 0 && (
          <ul className="font-mono text-[11px] opacity-90">
            {assigned.slice(0, 6).map((a, i) => (
              <li key={i}>
                {a.component_id}.{a.pin_role} → {summarize(a.new_target)}
              </li>
            ))}
            {assigned.length > 6 && <li>…and {assigned.length - 6} more</li>}
          </ul>
        )}
        {unresolved.length > 0 && (
          <ul className="text-[11px]">
            {unresolved.map((w, i) => (
              <li key={i}><span className="font-mono">[{w.code}]</span> {w.text}</li>
            ))}
          </ul>
        )}
        {warnings.length > 0 && (
          <ul className="text-[11px]">
            {warnings.map((w, i) => (
              <li key={i}><span className="font-mono">[{w.code}]</span> {w.text}</li>
            ))}
          </ul>
        )}
      </div>
      <button
        onClick={onDismiss}
        className="rounded border border-current/30 px-1.5 py-0.5 text-[11px] opacity-80 hover:opacity-100"
      >
        ✕
      </button>
    </div>
  );
}

function summarize(target: Record<string, unknown>): string {
  const kind = String(target.kind ?? "");
  if (kind === "gpio") return `gpio ${target.pin}`;
  if (kind === "rail") return `rail ${target.rail}`;
  if (kind === "bus") return `bus ${target.bus_id}`;
  if (kind === "expander_pin") return `${target.expander_id}.${target.number}`;
  return JSON.stringify(target);
}
