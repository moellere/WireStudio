import { useEffect, useMemo, useRef, useState } from "react";
import { Boxes, Download, Search, Trash2, Upload, X } from "lucide-react";
import { api } from "../api/client";
import type { AppliedSubstitution, Design, BuyListResponse, InventoryCheckResponse, InventoryEntry, InventorySubstitute } from "../types/api";
import { Button } from "./ui";

type Part = { id: string; name: string; kind: "component" | "module" };

const STATUS_STYLE: Record<string, string> = {
  have: "text-emerald-300 bg-emerald-500/10 ring-emerald-500/30",
  partial: "text-amber-300 bg-amber-500/10 ring-amber-500/30",
  need: "text-rose-300 bg-rose-500/10 ring-rose-500/30",
  assumed: "text-sky-300 bg-sky-500/10 ring-sky-500/30",
  untracked: "text-ink-faint bg-white/5 ring-white/10",
};

const PICK_GROUP_LABEL: Record<string, string> = {
  location: "",
  unlocated: "In stock, no location recorded",
  assumed: "Common values (not inventoried)",
  missing: "Not in the drawer",
};

/** "What's in my drawer": list/add/edit/remove inventory entries, and check the
 *  open design's BOM against what's on hand (have / partial / need). */
function headroomText(sub: InventorySubstitute): string {
  const parts: string[] = [];
  if (typeof sub.headroom?.v === "number") parts.push(`${sub.headroom.v.toFixed(1)}× V`);
  if (typeof sub.headroom?.i === "number") parts.push(`${sub.headroom.i.toFixed(1)}× I`);
  return parts.length ? `, ${parts.join(" ")} headroom` : "";
}

export function InventoryDialog({
  design,
  onClose,
  onApplySubstitute,
  onApplyAll,
}: {
  design?: Design | null;
  onClose: () => void;
  onApplySubstitute?: (keys: string[], mpn: string) => void;
  onApplyAll?: (applied: AppliedSubstitution[]) => void;
}) {
  const [entries, setEntries] = useState<InventoryEntry[]>([]);
  const [parts, setParts] = useState<Part[]>([]);
  const [search, setSearch] = useState("");
  const [check, setCheck] = useState<InventoryCheckResponse | null>(null);
  const [buy, setBuy] = useState<BuyListResponse | null>(null);
  const [buying, setBuying] = useState(false);
  const [applying, setApplying] = useState(false);
  const [appliedNote, setAppliedNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    void (async () => {
      try {
        const [inv, comps, mods] = await Promise.all([
          api.listInventory(),
          api.listComponents(),
          api.listModules(),
        ]);
        setEntries(inv);
        setParts([
          ...comps.map((c) => ({ id: c.id, name: c.name, kind: "component" as const })),
          ...mods.map((m) => ({ id: m.id, name: m.name, kind: "module" as const })),
        ]);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const inInventory = useMemo(() => {
    const ids = new Set<string>();
    for (const e of entries) ids.add(e.library_id);
    return ids;
  }, [entries]);

  // ⚡ Bolt: memoize parts lookup map to avoid O(N²) array traversals inside the render loop
  const partsMap = useMemo(() => {
    const map = new Map<string, string>();
    for (const p of parts) map.set(p.id, p.name);
    return map;
  }, [parts]);
  const nameOf = (id: string) => partsMap.get(id) ?? id;

  const matches = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return [];
    // ⚡ Bolt: Use a single-pass loop with early break instead of .filter().slice()
    // This avoids a full O(N) traversal and intermediate array allocations when searching large library lists.
    const results = [];
    for (const p of parts) {
      if (!inInventory.has(p.id) && (p.name.toLowerCase().includes(q) || p.id.includes(q))) {
        results.push(p);
        if (results.length === 8) break;
      }
    }
    return results;
  }, [search, parts, inInventory]);

  function fail(e: unknown) {
    setError(e instanceof Error ? e.message : String(e));
  }

  async function addPart(p: Part) {
    try {
      const entry = await api.setInventory(p.id, { kind: p.kind, quantity: 1 });
      setEntries((es) => [...es, entry].sort((a, b) => a.key.localeCompare(b.key)));
      setSearch("");
    } catch (e) {
      fail(e);
    }
  }

  function patch(key: string, fields: Partial<InventoryEntry>) {
    setEntries((es) => es.map((e) => (e.key === key ? { ...e, ...fields } : e)));
  }

  async function persist(entry: InventoryEntry) {
    try {
      const saved = await api.setInventory(entry.library_id, {
        kind: entry.kind,
        quantity: Math.max(0, Math.trunc(entry.quantity || 0)),
        min_quantity: Math.max(0, Math.trunc(entry.min_quantity || 0)),
        location: entry.location,
        note: entry.note,
      });
      setEntries((es) => es.map((e) => (e.key === saved.key ? saved : e)));
    } catch (e) {
      fail(e);
    }
  }

  async function remove(key: string) {
    try {
      await api.deleteInventory(key);
      setEntries((es) => es.filter((e) => e.key !== key));
    } catch (e) {
      fail(e);
    }
  }

  async function applyAll() {
    if (!design) return;
    setApplying(true);
    setError(null);
    try {
      const r = await api.applyInventorySubstitutions(design);
      onApplyAll?.(r.applied);
      setAppliedNote(
        r.applied.length === 0
          ? "Nothing to apply: no line has a proposal."
          : `Applied ${r.applied.length}: ${r.applied.map((a) => `${a.mpn} for ${a.refs.join(", ")}`).join("; ")}. Re-run the check to see the drawer against the new BOM.`,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setApplying(false);
    }
  }

  async function runCheck() {
    if (!design) return;
    try {
      setCheck(await api.checkDesignInventory(design));
    } catch (e) {
      fail(e);
    }
  }

  async function runBuyList() {
    if (!design) return;
    setBuying(true);
    try {
      setBuy(await api.buyList(design));
    } catch (e) {
      fail(e);
    } finally {
      setBuying(false);
    }
  }

  const fileRef = useRef<HTMLInputElement | null>(null);

  async function exportCsv() {
    try {
      const csv = await api.exportInventoryCsv();
      const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = "inventory.csv";
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      fail(e);
    }
  }

  async function importCsv(file: File) {
    try {
      const res = await api.importInventoryCsv(await file.text());
      setEntries(await api.listInventory());
      const done = `imported ${res.imported}, updated ${res.updated}`;
      setError(
        res.rejected.length
          ? `${done}; ${res.rejected.length} row(s) not used: ` +
            res.rejected.map((r) => (r.row ? `row ${r.row}: ${r.reason}` : r.reason)).join("; ")
          : null,
      );
    } catch (e) {
      fail(e);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex animate-overlay-in items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="flex max-h-[85vh] w-[min(720px,92vw)] animate-dialog-in flex-col overflow-hidden rounded-xl bg-surface-1 shadow-panel"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-line px-5 py-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-ink">
            <Boxes className="h-4 w-4 text-ink-dim" />
            Component Inventory
          </div>
          <div className="flex items-center gap-1">
            <button onClick={exportCsv} title="Export inventory as CSV" aria-label="Export CSV"
              className="rounded-md p-1.5 text-ink-faint transition-colors hover:bg-surface-2 hover:text-ink">
              <Download className="h-4 w-4" />
            </button>
            <button onClick={() => fileRef.current?.click()} title="Import inventory from CSV" aria-label="Import CSV"
              className="rounded-md p-1.5 text-ink-faint transition-colors hover:bg-surface-2 hover:text-ink">
              <Upload className="h-4 w-4" />
            </button>
            <input
              ref={fileRef}
              type="file"
              accept=".csv,text/csv"
              className="hidden"
              onChange={(ev) => {
                const f = ev.target.files?.[0];
                if (f) void importCsv(f);
                ev.target.value = "";
              }}
            />
            <button onClick={onClose} aria-label="Close" className="rounded-md p-1.5 text-ink-faint transition-colors hover:bg-surface-2 hover:text-ink">
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        <div className="space-y-4 overflow-y-auto px-5 py-4">
          {error && (
            <div className="rounded-md bg-rose-500/10 p-2 text-xs text-rose-200 ring-1 ring-rose-500/30">{error}</div>
          )}

          {/* Add a part */}
          <section>
            <div className="relative">
              <Search className="pointer-events-none absolute left-2 top-2.5 h-3.5 w-3.5 text-ink-faint" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Add a part — search components and modules…"
                className="w-full rounded-md border border-line bg-surface-1 py-1.5 pl-7 pr-2 text-xs text-ink placeholder:text-ink-ghost transition-colors focus:border-accent-500/60 focus:outline-none"
              />
            </div>
            {matches.length > 0 && (
              <ul className="mt-1 divide-y divide-line rounded-md border border-line">
                {matches.map((p) => (
                  <li key={`${p.kind}:${p.id}`}>
                    <button
                      onClick={() => addPart(p)}
                      className="flex w-full items-center justify-between px-2 py-1.5 text-left text-xs text-ink transition-colors hover:bg-surface-2"
                    >
                      <span>{p.name}</span>
                      <span className="ml-2 rounded bg-surface-2 px-1.5 py-0.5 text-[10px] text-ink-dim">{p.kind}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {/* Inventory list */}
          <section>
            {loading ? (
              <p className="text-xs text-ink-faint">Loading inventory…</p>
            ) : entries.length === 0 ? (
              <p className="text-xs text-ink-faint">No parts on hand yet. Search above to add one.</p>
            ) : (
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left text-[11px] uppercase tracking-wider text-ink-faint">
                    <th className="pb-1 font-medium">Part</th>
                    <th className="pb-1 font-medium w-16">Qty</th>
                    <th className="pb-1 font-medium w-16">Min</th>
                    <th className="pb-1 font-medium">Location</th>
                    <th className="pb-1 font-medium">Note</th>
                    <th className="pb-1"></th>
                  </tr>
                </thead>
                <tbody className="align-top">
                  {entries.map((e) => (
                    <tr key={e.key} className="border-t border-line">
                      <td className="py-1.5 pr-2 text-ink">
                        {e.kind === "part" ? e.mpn : nameOf(e.library_id)}
                        {e.kind !== "component" && (
                          <span className="ml-1 rounded bg-surface-2 px-1 py-0.5 text-[10px] text-ink-dim">{e.kind}</span>
                        )}
                        {e.kind === "part" && e.package && (
                          <span className="ml-1 text-[10px] text-ink-faint">{[e.family, e.polarity, e.package].filter(Boolean).join(" · ")}</span>
                        )}
                        {e.low_stock && (
                          <span className="ml-1 rounded bg-amber-500/10 px-1 py-0.5 text-[10px] text-amber-300 ring-1 ring-amber-500/30">low</span>
                        )}
                      </td>
                      <td className="py-1 pr-2">
                        <input
                          type="number"
                          min={0}
                          value={e.quantity}
                          onChange={(ev) => patch(e.key, { quantity: Number(ev.target.value) })}
                          onBlur={() => persist(e)}
                          className={`w-14 rounded-md border bg-surface-1 px-1.5 py-1 text-ink transition-colors focus:outline-none ${e.low_stock ? "border-amber-500/50 focus:border-amber-400" : "border-line focus:border-accent-500/60"}`}
                        />
                      </td>
                      <td className="py-1 pr-2">
                        <input
                          type="number"
                          min={0}
                          value={e.min_quantity}
                          title="Low-stock threshold (0 = none)"
                          onChange={(ev) => patch(e.key, { min_quantity: Number(ev.target.value) })}
                          onBlur={() => persist(e)}
                          className="w-14 rounded-md border border-line bg-surface-1 px-1.5 py-1 text-ink-faint transition-colors focus:border-accent-500/60 focus:text-ink focus:outline-none"
                        />
                      </td>
                      <td className="py-1 pr-2">
                        <input
                          value={e.location}
                          onChange={(ev) => patch(e.key, { location: ev.target.value })}
                          onBlur={() => persist(e)}
                          placeholder="bin / drawer"
                          className="w-full rounded-md border border-line bg-surface-1 px-1.5 py-1 text-ink placeholder:text-ink-ghost transition-colors focus:border-accent-500/60 focus:outline-none"
                        />
                      </td>
                      <td className="py-1 pr-2">
                        <input
                          value={e.note}
                          onChange={(ev) => patch(e.key, { note: ev.target.value })}
                          onBlur={() => persist(e)}
                          placeholder="—"
                          className="w-full rounded-md border border-line bg-surface-1 px-1.5 py-1 text-ink placeholder:text-ink-ghost transition-colors focus:border-accent-500/60 focus:outline-none"
                        />
                      </td>
                      <td className="py-1.5 text-right">
                        <button
                          onClick={() => remove(e.key)}
                          aria-label={`Remove ${nameOf(e.library_id)}`}
                          className="rounded-md p-1 text-ink-faint transition-colors hover:bg-surface-2 hover:text-rose-300"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          {/* Design BOM check */}
          {design && (
            <section className="border-t border-line pt-3">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-ink-dim">Check the open design</span>
                <span className="flex gap-1.5">
                  <Button size="sm" onClick={runCheck}>
                    Check BOM
                  </Button>
                  <Button size="sm" variant="secondary" onClick={runBuyList} disabled={buying}
                    title="What the drawer is short, priced on JLCPCB">
                    {buying ? "Pricing…" : "Buy list"}
                  </Button>
                </span>
              </div>
              {buy && (
                <div className="mt-2 space-y-1 text-xs">
                  {!buy.available && (
                    <p className="text-amber-300">JLCPCB unavailable{buy.reason ? `: ${buy.reason}` : ""}. Shortfalls listed unpriced.</p>
                  )}
                  {buy.lines.length === 0 ? (
                    <p className="text-ink-faint">Nothing to buy: the drawer covers this design.</p>
                  ) : (
                    <ul className="divide-y divide-line rounded-md border border-line">
                      {buy.lines.map((ln) => (
                        <li key={`${ln.kind}:${ln.label}`} className="flex items-center justify-between px-2 py-1">
                          <span className="text-ink">
                            {ln.shortfall}× {ln.label}
                            <span className="ml-1 text-ink-faint">{ln.refs.join(", ")}</span>
                          </span>
                          <span className="text-ink-dim">
                            {ln.status === "ok" && ln.lcsc ? (
                              <a className="text-accent-300 hover:underline" href={`https://jlcpcb.com/partdetail/${ln.lcsc}`} target="_blank" rel="noreferrer">
                                {ln.lcsc}
                              </a>
                            ) : null}
                            <span className="ml-1">{ln.note}</span>
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
              {check && (
                <div className="mt-2 space-y-2">
                  <div className="flex gap-2 text-[11px]">
                    {(["have", "partial", "need"] as const).map((s) => (
                      <span key={s} className={`rounded px-1.5 py-0.5 ring-1 ${STATUS_STYLE[s]}`}>
                        {check.summary[s] ?? 0} {s}
                      </span>
                    ))}
                  </div>
                  <ul className="divide-y divide-line rounded-md border border-line">
                    {check.lines.map((ln) => (
                      <li key={ln.library_id} className="flex items-center justify-between px-2 py-1 text-xs">
                        <span className="text-ink">{ln.name}</span>
                        <span className="flex items-center gap-2 text-ink-dim">
                          <span>{ln.on_hand}/{ln.needed}</span>
                          <span className={`rounded px-1.5 py-0.5 text-[10px] ring-1 ${STATUS_STYLE[ln.status] ?? ""}`}>
                            {ln.status}
                          </span>
                        </span>
                      </li>
                    ))}
                  </ul>
                  {check.parts.length > 0 && (
                    <>
                      <div className="flex items-center justify-between pt-1">
                        <span className="text-xs font-medium text-ink-dim">Discrete parts</span>
                        <div className="flex items-center gap-2 text-[11px]">
                          {onApplyAll && check.parts.some((ln) => ln.substitutes.length > 0 && ln.keys.length > 0) && (
                            <button
                              type="button"
                              className="text-accent-300 hover:underline disabled:opacity-50"
                              disabled={applying}
                              title="Set part_overrides to the best-ranked proposal on every short line at once"
                              onClick={applyAll}
                            >
                              {applying ? "Applying…" : "Use all suggested substitutes"}
                            </button>
                          )}
                          {(["have", "partial", "need", "assumed"] as const).map((s) =>
                            check.parts_summary[s] ? (
                              <span key={s} className={`rounded px-1.5 py-0.5 ring-1 ${STATUS_STYLE[s]}`}>
                                {check.parts_summary[s]} {s}
                              </span>
                            ) : null,
                          )}
                        </div>
                      </div>
                      {appliedNote && <p className="text-[11px] text-emerald-300/90">{appliedNote}</p>}
                      <ul className="divide-y divide-line rounded-md border border-line">
                        {check.parts.map((ln) => (
                          <li key={`${ln.family}:${ln.value}`} className="px-2 py-1 text-xs">
                            <div className="flex items-center justify-between">
                              <span className="text-ink">
                                {ln.value}
                                <span className="ml-1 text-ink-faint">{ln.refs.join(", ")}</span>
                                {ln.substituted_for.length > 0 && (
                                  <span className="ml-1 text-ink-faint">(for {ln.substituted_for.join(", ")})</span>
                                )}
                              </span>
                              <span className="flex items-center gap-2 text-ink-dim">
                                <span>{ln.on_hand}/{ln.needed}</span>
                                <span className={`rounded px-1.5 py-0.5 text-[10px] ring-1 ${STATUS_STYLE[ln.status] ?? ""}`}>
                                  {ln.status}
                                </span>
                              </span>
                            </div>
                            {ln.substitutes.length > 0 && (
                              <ul className="mt-1 space-y-0.5 border-l border-line pl-2 text-[11px]">
                                {ln.substitutes.map((sub) => (
                                  <li key={sub.key} className="text-ink-dim">
                                    <span className="text-ink">{sub.mpn}</span> could substitute ({sub.on_hand} on hand
                                    {sub.location ? `, ${sub.location}` : ""}{headroomText(sub)}). {sub.caveats.join("; ")}.
                                    {onApplySubstitute && ln.keys.length > 0 && (
                                      <button
                                        type="button"
                                        className="ml-1 text-accent-300 hover:underline"
                                        title={`Set part_overrides for ${ln.keys.join(", ")}; the BOM, CPL and schematic print ${sub.mpn}. Re-run the check afterwards.`}
                                        onClick={() => onApplySubstitute(ln.keys, sub.mpn)}
                                      >
                                        Use for {ln.refs.join(", ")}
                                      </button>
                                    )}
                                  </li>
                                ))}
                              </ul>
                            )}
                          </li>
                        ))}
                      </ul>
                    </>
                  )}
                  {check.pick_list.length > 0 && (
                    <>
                      <div className="pt-1 text-xs font-medium text-ink-dim">Pick list</div>
                      <ul className="space-y-1.5">
                        {check.pick_list.map((g) => (
                          <li key={`${g.kind}:${g.location}`} className="rounded-md border border-line px-2 py-1 text-xs">
                            <div className="text-ink">{PICK_GROUP_LABEL[g.kind] ?? g.location}{g.kind === "location" ? g.location : ""}</div>
                            <ul className="mt-0.5 text-[11px] text-ink-dim">
                              {g.items.map((i) => (
                                <li key={`${i.label}:${i.refs.join(",")}`}>
                                  {i.needed}× <span className="text-ink">{i.label}</span>
                                  <span className="ml-1 text-ink-faint">{i.refs.join(", ")}</span>
                                </li>
                              ))}
                            </ul>
                          </li>
                        ))}
                      </ul>
                    </>
                  )}
                </div>
              )}
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
