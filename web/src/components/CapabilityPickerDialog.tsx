import { useEffect, useMemo, useState, useCallback } from "react";
import { api, ApiError } from "../api/client";
import type { Recommendation, UseCaseEntry } from "../types/api";
import { Loading } from "./Status";
import { useDebouncedValue } from "../lib/debounce";
import { Dialog, FieldLabel, Input } from "./ui";

interface Props {
  /** True when the design has a board picked. We disable Add when there's
   *  no design yet because handleAddComponent needs board context. */
  designReady: boolean;
  /** Bus types already present on the design (e.g., ["i2c"], ["i2c", "spi"]).
   *  Drives the "match my buses" filter so an I2C-only design doesn't
   *  surface an SPI-only sensor in the top-pick slot. */
  designBusTypes: string[];
  onAdd: (libraryId: string) => Promise<void> | void;
  onClose: () => void;
}

const BUS_REQUIREMENT_KEYS: ReadonlySet<string> = new Set([
  "i2c", "spi", "uart", "i2s", "1wire",
]);

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
export function CapabilityPickerDialog({ designReady, designBusTypes, onAdd, onClose }: Props) {
  const [useCases, setUseCases] = useState<UseCaseEntry[] | null>(null);
  const [pickedCapability, setPickedCapability] = useState<string>("");
  const [freeText, setFreeText] = useState<string>("");
  const [matches, setMatches] = useState<Recommendation[] | null>(null);
  const [loadingMatches, setLoadingMatches] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState<string | null>(null); // library_id mid-add
  const [added, setAdded] = useState<Set<string>>(new Set());
  const [filterByBuses, setFilterByBuses] = useState<boolean>(true);
  /** library_id of the match whose "alternatives" disclosure is open. Only
   *  one expansion at a time -- a single open panel keeps the list compact
   *  and avoids the user having to scroll past several stacked panels. */
  const [expandedAlts, setExpandedAlts] = useState<string | null>(null);

  const designBusSet = useMemo(() => new Set(designBusTypes), [designBusTypes]);

  /**
   * Drop matches that require a bus the design doesn't already have. Library
   * components advertise these via `required_components` (e.g., "i2c", "spi");
   * non-bus tokens like "decoupling_caps" are passed through untouched.
   */
  const passesBusFilter = useCallback((rec: Recommendation): boolean => {
    if (!filterByBuses) return true;
    for (const req of rec.required_components) {
      if (BUS_REQUIREMENT_KEYS.has(req) && !designBusSet.has(req)) {
        return false;
      }
    }
    return true;
  }, [filterByBuses, designBusSet]);

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

  const debouncedQuery = useDebouncedValue(activeQuery, 300);

  // Run the recommender whenever the active query changes.
  useEffect(() => {
    if (!debouncedQuery) {
      setMatches(null);
      return;
    }
    let cancelled = false;
    setLoadingMatches(true);
    setError(null);
    (async () => {
      try {
        const r = await api.recommend({ query: debouncedQuery, limit: 8 });
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
  }, [debouncedQuery]);

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
  const visible = useMemo(() => matches ? matches.filter(passesBusFilter) : [], [matches, passesBusFilter]);


  return (
    <Dialog
      title="Add by function"
      subtitle="Pick a capability; we'll rank library components that provide it."
      onClose={onClose}
      maxWidth="max-w-3xl"
    >
      <div className="-mx-5 -my-4 grid h-[70vh] grid-cols-[14rem_1fr]">
        {/* Left: capability vocabulary + free text */}
        <div className="flex min-h-0 flex-col border-r border-line bg-surface-0/40">
          <div className="space-y-1 border-b border-line p-3">
            <FieldLabel>free text</FieldLabel>
            <Input
              type="text"
              value={freeText}
              onChange={(e) => setFreeText(e.target.value)}
              placeholder="e.g. door sensor"
              className="text-xs"
            />
            {freeText.trim() && (
              <p className="text-[11px] text-ink-faint">
                Free text overrides the picked capability below.
              </p>
            )}
          </div>
          <div className="flex-1 overflow-y-auto p-2">
            <div className="px-1 pb-1 text-[11px] uppercase tracking-wider text-ink-faint">
              library capabilities
            </div>
            {useCases === null ? (
              <Loading />
            ) : useCases.length === 0 ? (
              <div className="px-2 py-1 text-xs text-ink-faint">none</div>
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
                        className={`flex w-full items-center justify-between gap-2 rounded-md px-2 py-1 text-left text-xs transition-colors ${
                          active
                            ? "bg-accent-500/10 text-accent-200 ring-1 ring-accent-500/40"
                            : "text-ink hover:bg-surface-2"
                        }`}
                      >
                        <span className="truncate">{uc.use_case}</span>
                        <span className="shrink-0 rounded-md bg-surface-2 px-1 text-[10px] text-ink-dim">
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
          <div className="flex items-center justify-between border-b border-line px-4 py-2 text-xs text-ink-dim">
            <span>
              {activeQuery ? (
                <>
                  matches for{" "}
                  <code className="rounded-md bg-surface-2 px-1 text-ink">{activeQuery}</code>
                </>
              ) : (
                <>pick a capability or enter free text on the left</>
              )}
            </span>
            {designBusTypes.length > 0 && (
              <label
                className="flex shrink-0 cursor-pointer items-center gap-1 text-[11px] text-ink-dim hover:text-ink"
                title={`Hide matches that need a bus your design lacks (current: ${designBusTypes.join(", ")})`}
              >
                <input
                  type="checkbox"
                  checked={filterByBuses}
                  onChange={(e) => setFilterByBuses(e.target.checked)}
                  className="h-3 w-3"
                />
                match my buses ({designBusTypes.join("/")})
              </label>
            )}
          </div>
          <div className="flex-1 overflow-y-auto p-3">
            {!designReady && (
              <div className="mb-2 rounded-md bg-amber-500/10 px-2 py-1.5 text-[11px] text-amber-200 ring-1 ring-amber-500/30">
                No design loaded — pick or create one before adding components.
              </div>
            )}
            {error && (
              <div className="mb-2 rounded-md bg-rose-500/10 px-2 py-1.5 text-[11px] text-rose-200 ring-1 ring-rose-500/30">
                {error}
              </div>
            )}
            {(() => {
              if (loadingMatches) {
                return <div className="text-xs text-ink-faint">searching…</div>;
              }
              if (!activeQuery) return null;
              if (!matches || matches.length === 0) {
                return (
                  <div className="text-xs text-ink-faint">
                    no library components match{" "}
                    <code className="rounded-md bg-surface-2 px-1">{activeQuery}</code>.
                  </div>
                );
              }
              const hiddenByFilter = matches.length - visible.length;
              if (visible.length === 0) {
                return (
                  <div className="text-xs text-ink-faint">
                    {hiddenByFilter} match{hiddenByFilter === 1 ? "" : "es"} hidden
                    by the bus filter. Uncheck "match my buses" to see them.
                  </div>
                );
              }
              return (
                <>
                  {hiddenByFilter > 0 && (
                    <div className="mb-2 text-[11px] text-ink-faint">
                      {hiddenByFilter} hidden by the bus filter.
                    </div>
                  )}
                  <ul className="space-y-2">
                    {visible.map((m, idx) => {
                  const isAdded = added.has(m.library_id);
                  const isAdding = adding === m.library_id;
                  // ⚡ Bolt: avoid allocating N arrays in an O(N^2) render loop
                  const alternativesCount = visible.length > 0 ? visible.length - 1 : 0;
                  const altsOpen = expandedAlts === m.library_id;
                  return (
                    <li
                      key={m.library_id}
                      className="rounded-md border border-line bg-surface-2/40 p-2"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <div className="flex items-baseline gap-2">
                            {idx === 0 && (
                              <span className="rounded-md bg-emerald-500/10 px-1 text-[10px] uppercase tracking-wider text-emerald-200 ring-1 ring-emerald-500/30">
                                top pick
                              </span>
                            )}
                            <span className="text-sm text-ink">{m.name}</span>
                            <code className="text-[11px] text-ink-faint">{m.library_id}</code>
                          </div>
                          <div className="mt-0.5 text-[11px] text-ink-dim">
                            {m.category}
                            {m.use_cases.length > 0 && ` · ${m.use_cases.join(", ")}`}
                          </div>
                          {m.rationale && (
                            <div className="mt-0.5 text-[11px] text-ink-faint">{m.rationale}</div>
                          )}
                          <div className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-ink-faint">
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
                          {alternativesCount > 0 && (
                            <button
                              type="button"
                              onClick={() => setExpandedAlts(altsOpen ? null : m.library_id)}
                              aria-expanded={altsOpen}
                              className="mt-1 text-[11px] text-ink-faint hover:text-ink-dim"
                            >
                              {altsOpen ? "▾" : "▸"} {alternativesCount} alternative
                              {alternativesCount === 1 ? "" : "s"}
                            </button>
                          )}
                          {altsOpen && (
                            <ul className="mt-1 space-y-0.5 border-l border-line pl-2">
                              {visible.map((alt) => alt.library_id === m.library_id ? null : (
                                <li
                                  key={alt.library_id}
                                  className="flex items-baseline justify-between gap-2 text-[11px]"
                                >
                                  <span className="min-w-0 truncate">
                                    <span className="text-ink-dim">{alt.name}</span>
                                    <code className="ml-1 text-ink-faint">{alt.library_id}</code>
                                    {alt.required_components.length > 0 && (
                                      <span className="ml-1 text-ink-faint">
                                        · {alt.required_components.join(", ")}
                                      </span>
                                    )}
                                    {alt.current_ma_peak != null && (
                                      <span className="ml-1 text-ink-faint">
                                        · {alt.current_ma_peak}mA
                                      </span>
                                    )}
                                  </span>
                                  <span className="shrink-0 text-ink-faint">
                                    score {alt.score}{" "}
                                    <span
                                      className={
                                        alt.score < m.score
                                          ? "text-ink-ghost"
                                          : "text-emerald-300"
                                      }
                                    >
                                      ({alt.score >= m.score ? "+" : ""}
                                      {(alt.score - m.score).toFixed(1)})
                                    </span>
                                  </span>
                                </li>
                              ))}
                            </ul>
                          )}
                        </div>
                        <div className="flex shrink-0 flex-col items-end gap-1">
                          <span className="text-[10px] text-ink-faint">score {m.score}</span>
                          <button
                            disabled={!designReady || isAdding}
                            onClick={() => handleAdd(m.library_id)}
                            className={`rounded-md px-2 py-1 text-xs transition-colors disabled:opacity-40 ${
                              isAdded
                                ? "bg-emerald-500/15 text-emerald-100 ring-1 ring-emerald-500/40"
                                : "bg-accent-600 text-accent-50 shadow-pop enabled:hover:bg-accent-500"
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
                </>
              );
            })()}
          </div>
        </div>
      </div>
    </Dialog>
  );
}
