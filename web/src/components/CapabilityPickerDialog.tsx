import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../api/client";
import type { Recommendation, UseCaseEntry } from "../types/api";

interface Props {
  /** True when the design has a board picked. We disable Add when there's
   *  no design yet because handleAddComponent needs board context. */
  designReady: boolean;
  onAdd: (libraryId: string) => Promise<void> | void;
  onClose: () => void;
}

/**
 * "Add by function" picker. Two columns:
 *
 *   Left  — canonical use_cases from the library (with counts) plus a
 *           free-text fallback. Picking a row drives the recommend call.
 *   Right — ranked component matches with rationale, current draw, and
 *           a one-click "Add to design" button.
 *
 * Reuses GET /library/use_cases for the vocabulary and POST
 * /library/recommend for the ranking. The latter is the same endpoint
 * the agent uses; this dialog just exposes it to the human.
 */
export function CapabilityPickerDialog({ designReady, onAdd, onClose }: Props) {
  const [useCases, setUseCases] = useState<UseCaseEntry[] | null>(null);
  const [pickedCapability, setPickedCapability] = useState<string>("");
  const [freeText, setFreeText] = useState<string>("");
  const [matches, setMatches] = useState<Recommendation[] | null>(null);
  const [loadingMatches, setLoadingMatches] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState<string | null>(null); // library_id mid-add
  const [added, setAdded] = useState<Set<string>>(new Set());

  // Bootstrap the use-case list.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const rows = await api.listUseCases();
        if (!cancelled) setUseCases(rows);
      } catch (e) {
        if (cancelled) return;
        const msg = e instanceof ApiError ? `${e.status}: ${e.message}` :
          e instanceof Error ? e.message : String(e);
        setError(msg);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // The active query is whichever of (capability chip, free text) is non-empty.
  const activeQuery = useMemo(
    () => freeText.trim() || pickedCapability,
    [freeText, pickedCapability],
  );

  // Run the recommender whenever the active query changes.
  useEffect(() => {
    if (!activeQuery) {
      setMatches(null);
      return;
    }
    let cancelled = false;
    setLoadingMatches(true);
    setError(null);
    (async () => {
      try {
        const r = await api.recommend({ query: activeQuery, limit: 8 });
        if (!cancelled) setMatches(r.matches);
      } catch (e) {
        if (cancelled) return;
        const msg = e instanceof ApiError ? `${e.status}: ${e.message}` :
          e instanceof Error ? e.message : String(e);
        setError(msg);
      } finally {
        if (!cancelled) setLoadingMatches(false);
      }
    })();
    return () => { cancelled = true; };
  }, [activeQuery]);

  async function handleAdd(libraryId: string) {
    setAdding(libraryId);
    try {
      await onAdd(libraryId);
      setAdded((prev) => new Set(prev).add(libraryId));
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
    } finally {
      setAdding(null);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="m-4 flex max-h-[85vh] w-full max-w-3xl flex-col overflow-hidden rounded-lg border border-zinc-800 bg-zinc-950 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-3">
          <div>
            <div className="text-sm font-semibold text-zinc-100">Add by function</div>
            <div className="text-xs text-zinc-500">
              Pick a capability; we'll rank library components that provide it.
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded border border-zinc-800 px-2 py-1 text-xs text-zinc-300 hover:bg-zinc-900"
          >
            Close
          </button>
        </div>

        <div className="grid min-h-0 flex-1 grid-cols-[14rem_1fr]">
          {/* Left: capability vocabulary + free text */}
          <div className="flex min-h-0 flex-col border-r border-zinc-800 bg-zinc-950/60">
            <div className="space-y-1 border-b border-zinc-800 p-3">
              <label className="block text-[11px] uppercase tracking-wide text-zinc-500">
                free text
              </label>
              <input
                type="text"
                value={freeText}
                onChange={(e) => setFreeText(e.target.value)}
                placeholder="e.g. door sensor"
                className="w-full rounded border border-zinc-800 bg-zinc-900 px-2 py-1 text-xs text-zinc-100 focus:border-zinc-600 focus:outline-none"
              />
              {freeText.trim() && (
                <p className="text-[11px] text-zinc-500">
                  Free text overrides the picked capability below.
                </p>
              )}
            </div>
            <div className="flex-1 overflow-y-auto p-2">
              <div className="px-1 pb-1 text-[11px] uppercase tracking-wide text-zinc-500">
                library capabilities
              </div>
              {useCases === null ? (
                <div className="px-2 py-1 text-xs text-zinc-500">loading…</div>
              ) : useCases.length === 0 ? (
                <div className="px-2 py-1 text-xs text-zinc-500">none</div>
              ) : (
                <ul className="space-y-0.5">
                  {useCases.map((uc) => {
                    const active = !freeText.trim() && pickedCapability === uc.use_case;
                    return (
                      <li key={uc.use_case}>
                        <button
                          onClick={() => setPickedCapability(uc.use_case)}
                          title={
                            uc.example_components.length
                              ? `e.g. ${uc.example_components.join(", ")}`
                              : undefined
                          }
                          className={`flex w-full items-center justify-between gap-2 rounded px-2 py-1 text-left text-xs transition-colors ${
                            active
                              ? "bg-blue-500/15 text-blue-100 ring-1 ring-blue-400/40"
                              : "text-zinc-200 hover:bg-zinc-900"
                          }`}
                        >
                          <span className="truncate">{uc.use_case}</span>
                          <span className="shrink-0 rounded bg-zinc-800 px-1 text-[10px] text-zinc-400">
                            {uc.count}
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          </div>

          {/* Right: ranked results */}
          <div className="flex min-h-0 flex-col">
            <div className="border-b border-zinc-800 px-4 py-2 text-xs text-zinc-400">
              {activeQuery ? (
                <span>
                  matches for{" "}
                  <code className="rounded bg-zinc-800 px-1 text-zinc-100">{activeQuery}</code>
                </span>
              ) : (
                <span>pick a capability or enter free text on the left</span>
              )}
            </div>
            <div className="flex-1 overflow-y-auto p-3">
              {!designReady && (
                <div className="mb-2 rounded border border-amber-700/40 bg-amber-900/15 px-2 py-1.5 text-[11px] text-amber-200">
                  No design loaded — pick or create one before adding components.
                </div>
              )}
              {error && (
                <div className="mb-2 rounded border border-rose-700/40 bg-rose-900/15 px-2 py-1.5 text-[11px] text-rose-200">
                  {error}
                </div>
              )}
              {loadingMatches ? (
                <div className="text-xs text-zinc-500">searching…</div>
              ) : !activeQuery ? null : matches === null || matches.length === 0 ? (
                <div className="text-xs text-zinc-500">
                  no library components match{" "}
                  <code className="rounded bg-zinc-800 px-1">{activeQuery}</code>.
                </div>
              ) : (
                <ul className="space-y-2">
                  {matches.map((m, idx) => {
                    const isAdded = added.has(m.library_id);
                    const isAdding = adding === m.library_id;
                    return (
                      <li
                        key={m.library_id}
                        className="rounded border border-zinc-800 bg-zinc-900/40 p-2"
                      >
                        <div className="flex items-start justify-between gap-2">
                          <div className="min-w-0">
                            <div className="flex items-baseline gap-2">
                              {idx === 0 && (
                                <span className="rounded bg-emerald-500/15 px-1 text-[10px] uppercase tracking-wide text-emerald-200 ring-1 ring-emerald-400/30">
                                  top pick
                                </span>
                              )}
                              <span className="text-sm text-zinc-100">{m.name}</span>
                              <code className="text-[11px] text-zinc-500">{m.library_id}</code>
                            </div>
                            <div className="mt-0.5 text-[11px] text-zinc-400">
                              {m.category}
                              {m.use_cases.length > 0 && ` · ${m.use_cases.join(", ")}`}
                            </div>
                            {m.rationale && (
                              <div className="mt-0.5 text-[11px] text-zinc-500">{m.rationale}</div>
                            )}
                            <div className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-zinc-500">
                              {m.required_components.length > 0 && (
                                <span>needs: {m.required_components.join(", ")}</span>
                              )}
                              {m.current_ma_peak != null && (
                                <span>{m.current_ma_peak}mA peak</span>
                              )}
                              {(m.vcc_min != null || m.vcc_max != null) && (
                                <span>
                                  Vcc {m.vcc_min ?? "?"}–{m.vcc_max ?? "?"}V
                                </span>
                              )}
                            </div>
                          </div>
                          <div className="flex shrink-0 flex-col items-end gap-1">
                            <span className="text-[10px] text-zinc-500">score {m.score}</span>
                            <button
                              disabled={!designReady || isAdding}
                              onClick={() => handleAdd(m.library_id)}
                              className={`rounded px-2 py-1 text-xs ring-1 transition-colors disabled:opacity-40 ${
                                isAdded
                                  ? "bg-emerald-500/15 text-emerald-100 ring-emerald-400/40"
                                  : "bg-blue-500/15 text-blue-100 ring-blue-400/40 enabled:hover:bg-blue-500/25"
                              }`}
                            >
                              {isAdding ? "Adding…" : isAdded ? "Added ✓" : "Add"}
                            </button>
                          </div>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
