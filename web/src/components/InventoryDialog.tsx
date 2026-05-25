import { useEffect, useMemo, useState } from "react";
import { Boxes, Search, Trash2, X } from "lucide-react";
import { api } from "../api/client";
import type { Design, InventoryCheckResponse, InventoryEntry } from "../types/api";

type Part = { id: string; name: string; kind: "component" | "module" };

const STATUS_STYLE: Record<string, string> = {
  have: "text-emerald-300 bg-emerald-500/10 ring-emerald-400/30",
  partial: "text-amber-300 bg-amber-500/10 ring-amber-400/30",
  need: "text-rose-300 bg-rose-500/10 ring-rose-400/30",
};

/** "What's in my drawer": list/add/edit/remove inventory entries, and check the
 *  open design's BOM against what's on hand (have / partial / need). */
export function InventoryDialog({ design, onClose }: { design?: Design | null; onClose: () => void }) {
  const [entries, setEntries] = useState<InventoryEntry[]>([]);
  const [parts, setParts] = useState<Part[]>([]);
  const [search, setSearch] = useState("");
  const [check, setCheck] = useState<InventoryCheckResponse | null>(null);
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

  const inInventory = useMemo(() => new Set(entries.map((e) => e.library_id)), [entries]);
  const nameOf = (id: string) => parts.find((p) => p.id === id)?.name ?? id;

  const matches = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return [];
    return parts
      .filter((p) => !inInventory.has(p.id) && (p.name.toLowerCase().includes(q) || p.id.includes(q)))
      .slice(0, 8);
  }, [search, parts, inInventory]);

  function fail(e: unknown) {
    setError(e instanceof Error ? e.message : String(e));
  }

  async function addPart(p: Part) {
    try {
      const entry = await api.setInventory(p.id, { kind: p.kind, quantity: 1 });
      setEntries((es) => [...es, entry].sort((a, b) => a.library_id.localeCompare(b.library_id)));
      setSearch("");
    } catch (e) {
      fail(e);
    }
  }

  function patch(id: string, fields: Partial<InventoryEntry>) {
    setEntries((es) => es.map((e) => (e.library_id === id ? { ...e, ...fields } : e)));
  }

  async function persist(entry: InventoryEntry) {
    try {
      const saved = await api.setInventory(entry.library_id, {
        kind: entry.kind,
        quantity: Math.max(0, Math.trunc(entry.quantity || 0)),
        location: entry.location,
        note: entry.note,
      });
      setEntries((es) => es.map((e) => (e.library_id === saved.library_id ? saved : e)));
    } catch (e) {
      fail(e);
    }
  }

  async function remove(id: string) {
    try {
      await api.deleteInventory(id);
      setEntries((es) => es.filter((e) => e.library_id !== id));
    } catch (e) {
      fail(e);
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

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="flex max-h-[85vh] w-[min(720px,92vw)] flex-col overflow-hidden rounded-lg border border-zinc-800 bg-zinc-950 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-3">
          <div className="flex items-center gap-2 text-sm font-medium text-zinc-100">
            <Boxes className="h-4 w-4 text-zinc-400" />
            Component Inventory
          </div>
          <button onClick={onClose} aria-label="Close" className="rounded p-1 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-4 overflow-y-auto px-4 py-3">
          {error && (
            <div className="rounded-md border border-rose-500/40 bg-rose-500/10 p-2 text-xs text-rose-200">{error}</div>
          )}

          {/* Add a part */}
          <section>
            <div className="relative">
              <Search className="pointer-events-none absolute left-2 top-2.5 h-3.5 w-3.5 text-zinc-500" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Add a part — search components and modules…"
                className="w-full rounded-md border border-zinc-800 bg-zinc-900 py-1.5 pl-7 pr-2 text-xs text-zinc-100 placeholder:text-zinc-600 focus:border-zinc-600 focus:outline-none"
              />
            </div>
            {matches.length > 0 && (
              <ul className="mt-1 divide-y divide-zinc-800 rounded-md border border-zinc-800">
                {matches.map((p) => (
                  <li key={`${p.kind}:${p.id}`}>
                    <button
                      onClick={() => addPart(p)}
                      className="flex w-full items-center justify-between px-2 py-1.5 text-left text-xs text-zinc-200 hover:bg-zinc-900"
                    >
                      <span>{p.name}</span>
                      <span className="ml-2 rounded bg-zinc-800 px-1.5 py-0.5 text-[10px] text-zinc-400">{p.kind}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {/* Inventory list */}
          <section>
            {loading ? (
              <p className="text-xs text-zinc-500">Loading inventory…</p>
            ) : entries.length === 0 ? (
              <p className="text-xs text-zinc-500">No parts on hand yet. Search above to add one.</p>
            ) : (
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left text-[11px] uppercase tracking-wide text-zinc-500">
                    <th className="pb-1 font-medium">Part</th>
                    <th className="pb-1 font-medium w-16">Qty</th>
                    <th className="pb-1 font-medium">Location</th>
                    <th className="pb-1 font-medium">Note</th>
                    <th className="pb-1"></th>
                  </tr>
                </thead>
                <tbody className="align-top">
                  {entries.map((e) => (
                    <tr key={e.library_id} className="border-t border-zinc-900">
                      <td className="py-1.5 pr-2 text-zinc-200">
                        {nameOf(e.library_id)}
                        {e.kind === "module" && (
                          <span className="ml-1 rounded bg-zinc-800 px-1 py-0.5 text-[10px] text-zinc-400">module</span>
                        )}
                      </td>
                      <td className="py-1 pr-2">
                        <input
                          type="number"
                          min={0}
                          value={e.quantity}
                          onChange={(ev) => patch(e.library_id, { quantity: Number(ev.target.value) })}
                          onBlur={() => persist(e)}
                          className="w-14 rounded border border-zinc-800 bg-zinc-900 px-1.5 py-1 text-zinc-100 focus:border-zinc-600 focus:outline-none"
                        />
                      </td>
                      <td className="py-1 pr-2">
                        <input
                          value={e.location}
                          onChange={(ev) => patch(e.library_id, { location: ev.target.value })}
                          onBlur={() => persist(e)}
                          placeholder="bin / drawer"
                          className="w-full rounded border border-zinc-800 bg-zinc-900 px-1.5 py-1 text-zinc-100 placeholder:text-zinc-600 focus:border-zinc-600 focus:outline-none"
                        />
                      </td>
                      <td className="py-1 pr-2">
                        <input
                          value={e.note}
                          onChange={(ev) => patch(e.library_id, { note: ev.target.value })}
                          onBlur={() => persist(e)}
                          placeholder="—"
                          className="w-full rounded border border-zinc-800 bg-zinc-900 px-1.5 py-1 text-zinc-100 placeholder:text-zinc-600 focus:border-zinc-600 focus:outline-none"
                        />
                      </td>
                      <td className="py-1.5 text-right">
                        <button
                          onClick={() => remove(e.library_id)}
                          aria-label={`Remove ${nameOf(e.library_id)}`}
                          className="rounded p-1 text-zinc-500 hover:bg-zinc-800 hover:text-rose-300"
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
            <section className="border-t border-zinc-800 pt-3">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-zinc-300">Check the open design</span>
                <button
                  onClick={runCheck}
                  className="rounded-md border border-zinc-800 px-2 py-1 text-xs text-zinc-200 hover:bg-zinc-900"
                >
                  Check BOM
                </button>
              </div>
              {check && (
                <div className="mt-2 space-y-2">
                  <div className="flex gap-2 text-[11px]">
                    {(["have", "partial", "need"] as const).map((s) => (
                      <span key={s} className={`rounded px-1.5 py-0.5 ring-1 ${STATUS_STYLE[s]}`}>
                        {check.summary[s] ?? 0} {s}
                      </span>
                    ))}
                  </div>
                  <ul className="divide-y divide-zinc-900 rounded-md border border-zinc-800">
                    {check.lines.map((ln) => (
                      <li key={ln.library_id} className="flex items-center justify-between px-2 py-1 text-xs">
                        <span className="text-zinc-200">{ln.name}</span>
                        <span className="flex items-center gap-2 text-zinc-400">
                          <span>{ln.on_hand}/{ln.needed}</span>
                          <span className={`rounded px-1.5 py-0.5 text-[10px] ring-1 ${STATUS_STYLE[ln.status] ?? ""}`}>
                            {ln.status}
                          </span>
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
