import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import type { CompatibilityWarning, Design, PinAssignment, SolverWarning } from "../types/api";
import {
  addWarning,
  readWarnings,
  removeWarning,
  updateWarning,
  type DesignWarning,
} from "../lib/design";
import { SolveResultBanner } from "./SolveResultBanner";
import { CompatibilityRow, Input, Select } from "./ui";

export interface SolveResult {
  assigned: PinAssignment[];
  unresolved: SolverWarning[];
  warnings: SolverWarning[];
}

type Tab = "compatibility" | "warnings" | "solver";

const COLLAPSED_KEY = "wirestudio:ui:problems-collapsed";

function readCollapsed(): boolean {
  try {
    return window.localStorage.getItem(COLLAPSED_KEY) === "1";
  } catch {
    return false;
  }
}

interface Props {
  design: Design;
  compatibilityWarnings: CompatibilityWarning[];
  solve: SolveResult | null;
  onDismissSolve: () => void;
  onDesignChange: (updater: (d: Design) => Design) => void;
  /** Bump to open the panel on its Compatibility tab. */
  showCompatibility?: number;
}

export function ProblemsPanel({
  design, compatibilityWarnings, solve, onDismissSolve, onDesignChange, showCompatibility = 0,
}: Props) {
  const [tab, setTab] = useState<Tab>("compatibility");
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const warnings = useMemo(() => readWarnings(design), [design]);

  useEffect(() => {
    try {
      window.localStorage.setItem(COLLAPSED_KEY, collapsed ? "1" : "0");
    } catch {
      // In-memory state still works for this session.
    }
  }, [collapsed]);

  useEffect(() => {
    if (!solve) return;
    setTab("solver");
    setCollapsed(false);
  }, [solve]);

  useEffect(() => {
    if (showCompatibility === 0) return;
    setTab("compatibility");
    setCollapsed(false);
  }, [showCompatibility]);

  const compatTone = compatibilityWarnings.some((w) => w.severity === "error")
    ? "rose"
    : compatibilityWarnings.some((w) => w.severity === "warn")
      ? "amber"
      : null;
  const solveIssues = solve ? solve.unresolved.length + solve.warnings.length : 0;
  const solveSummary = solve
    ? `Solver assigned ${solve.assigned.length} pin${solve.assigned.length === 1 ? "" : "s"}` +
      (solveIssues ? ` · ${solveIssues} issue${solveIssues === 1 ? "" : "s"}` : "")
    : null;

  function pick(t: Tab) {
    setTab(t);
    setCollapsed(false);
  }

  return (
    <div className={`flex min-h-0 flex-col border-t border-line bg-surface-0 ${collapsed ? "" : "h-52"}`}>
      <div className="flex items-center justify-between border-b border-line pr-2 text-xs">
        <div role="tablist" aria-label="Problems" className="flex">
          <ProblemTab active={!collapsed && tab === "compatibility"} onClick={() => pick("compatibility")} count={compatibilityWarnings.length} tone={compatTone}>
            Compatibility
          </ProblemTab>
          <ProblemTab active={!collapsed && tab === "warnings"} onClick={() => pick("warnings")} count={warnings.length} tone={null}>
            Warnings
          </ProblemTab>
          <ProblemTab active={!collapsed && tab === "solver"} onClick={() => pick("solver")} count={solveIssues} tone={solveIssues ? "amber" : null}>
            Solver
          </ProblemTab>
        </div>
        <div className="flex min-w-0 items-center gap-3">
          {solveSummary && <span className="truncate text-[11px] text-ink-faint">{solveSummary}</span>}
          <button
            onClick={() => setCollapsed((c) => !c)}
            aria-label={collapsed ? "Expand problems" : "Collapse problems"}
            aria-expanded={!collapsed}
            className="rounded-md p-1 text-ink-faint transition-colors hover:bg-surface-2 hover:text-ink"
          >
            <ChevronDown className={`h-3.5 w-3.5 transition-transform ${collapsed ? "rotate-180" : ""}`} />
          </button>
        </div>
      </div>

      {!collapsed && (
        <div role="tabpanel" className="min-h-0 flex-1 overflow-auto p-3 text-sm text-ink-dim">
          {tab === "compatibility" && (
            compatibilityWarnings.length > 0
              ? <CompatibilityList warnings={compatibilityWarnings} />
              : <div className="text-xs text-ink-faint">The checker found nothing on this design.</div>
          )}
          {tab === "warnings" && (
            <WarningList
              items={warnings}
              onUpdate={(i, patch) => onDesignChange((d) => updateWarning(d, i, patch))}
              onAdd={() => onDesignChange((d) => addWarning(d))}
              onRemove={(i) => onDesignChange((d) => removeWarning(d, i))}
            />
          )}
          {tab === "solver" && (
            solve
              ? (
                <div className="-m-3">
                  <SolveResultBanner
                    assigned={solve.assigned}
                    unresolved={solve.unresolved}
                    warnings={solve.warnings}
                    onDismiss={onDismissSolve}
                  />
                </div>
              )
              : <div className="text-xs text-ink-faint">Run Solve pins to see what it assigns.</div>
          )}
        </div>
      )}
    </div>
  );
}

function ProblemTab({
  active, onClick, count, tone, children,
}: {
  active: boolean;
  onClick: () => void;
  count: number;
  tone: "rose" | "amber" | null;
  children: ReactNode;
}) {
  const badge = tone === "rose"
    ? "bg-rose-500/15 text-rose-300"
    : tone === "amber"
      ? "bg-amber-500/15 text-amber-300"
      : "text-ink-faint";
  return (
    <button
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={`flex items-center gap-1.5 px-3 py-2 font-medium transition-colors ${
        active
          ? "border-b-2 border-accent-500 text-ink"
          : "border-b-2 border-transparent text-ink-faint hover:text-ink-dim"
      }`}
    >
      {children}
      {count > 0 && <span className={`rounded px-1 font-mono text-[10px] ${badge}`}>{count}</span>}
    </button>
  );
}

export function CompatibilityList({ warnings }: { warnings: CompatibilityWarning[] }) {
  return (
    <ul className="space-y-1.5">
      {warnings.map((w, i) => (
        <CompatibilityRow key={i} severity={w.severity} code={w.code} where={`${w.pin} · ${w.component_id}.${w.pin_role}`}>
          {w.message}
        </CompatibilityRow>
      ))}
    </ul>
  );
}

function WarningList({
  items, onUpdate, onAdd, onRemove,
}: {
  items: DesignWarning[];
  onUpdate: (i: number, patch: Partial<DesignWarning>) => void;
  onAdd: () => void;
  onRemove: (i: number) => void;
}) {
  return (
    <div className="space-y-2">
      {items.map((w, i) => (
        <div
          key={i}
          className={`rounded-md border p-2 ${
            w.level === "warn"
              ? "border-amber-500/40 bg-amber-500/5"
              : w.level === "error"
                ? "border-rose-500/40 bg-rose-500/10"
                : "border-line bg-surface-2/40"
          }`}
        >
          <div className="mb-1 flex items-center gap-2">
            <Select
              aria-label="Level"
              value={w.level}
              onChange={(e) => onUpdate(i, { level: e.target.value as DesignWarning["level"] })}
              className="w-20 shrink-0"
            >
              {(["info", "warn", "error"] as const).map((k) => (
                <option key={k} value={k}>{k}</option>
              ))}
            </Select>
            <Input
              compact
              mono
              type="text"
              aria-label="Code"
              value={w.code}
              onChange={(e) => onUpdate(i, { code: e.target.value })}
              placeholder="code"
              className="flex-1"
            />
            <button
              onClick={() => onRemove(i)}
              className="flex h-[26px] w-[26px] shrink-0 items-center justify-center rounded-md border border-line text-xs text-ink-faint transition-colors hover:border-rose-500/40 hover:bg-rose-500/10 hover:text-rose-300"
              title="Remove warning"
            >
              ✕
            </button>
          </div>
          <textarea
            value={w.text}
            onChange={(e) => onUpdate(i, { text: e.target.value })}
            rows={2}
            className="w-full resize-none rounded-md border border-line bg-surface-1 px-2 py-1 text-xs text-ink focus:border-accent-500/60 focus:outline-none"
          />
        </div>
      ))}
      <button
        onClick={onAdd}
        className="h-[26px] w-full rounded-md border border-dashed border-line px-2 text-xs text-ink-faint hover:border-line-strong hover:text-ink-dim"
      >
        + Add warning
      </button>
    </div>
  );
}
