import { useMemo, useState } from "react";
import { FolderHeart, FolderOpen, Cpu, Component } from "lucide-react";
import type { BoardSummary, ComponentSummary, ExampleSummary, SavedDesignSummary } from "../types/api";

type Tab = "examples" | "saved" | "boards" | "components";

interface Props {
  examples: ExampleSummary[] | null;
  saved: SavedDesignSummary[] | null;
  boards: BoardSummary[] | null;
  components: ComponentSummary[] | null;
  selectedExample: string | null;
  selectedSaved: string | null;
  onSelectExample: (id: string) => void;
  onSelectSaved: (id: string) => void;
  onDeleteSaved: (id: string) => void;
  onSelectBoard: (id: string) => void;
  onSelectComponent: (id: string) => void;
}

export function LeftSidebar(props: Props) {
  const [tab, setTab] = useState<Tab>("examples");
  const [search, setSearch] = useState("");

  return (
    <aside className="flex min-h-0 flex-col border-r border-zinc-800 bg-zinc-950">
      <div className="flex border-b border-zinc-800 p-2 gap-1 bg-zinc-950">
        {(["examples", "saved", "boards", "components"] as const).map((t) => {
          const Icon = t === "examples" ? FolderOpen : t === "saved" ? FolderHeart : t === "boards" ? Cpu : Component;
          return (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`flex flex-1 flex-col items-center gap-1 rounded-md py-2 transition-colors ${
                tab === t
                  ? "bg-zinc-800/80 text-zinc-100 ring-1 ring-zinc-700/50"
                  : "text-zinc-400 hover:bg-zinc-900 hover:text-zinc-200"
              }`}
              title={t.charAt(0).toUpperCase() + t.slice(1)}
            >
              <Icon className="h-4 w-4" />
              <span className="text-[10px] font-medium capitalize tracking-wide">
                {t}
                {t === "saved" && props.saved && props.saved.length > 0 && (
                  <span className="ml-1 opacity-70">({props.saved.length})</span>
                )}
              </span>
            </button>
          );
        })}
      </div>

      <div className="p-3 pb-2">
        <div className="relative">
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={`Filter ${tab}...`}
            className="w-full rounded-md border border-zinc-800 bg-zinc-900/50 px-3 py-1.5 text-xs text-zinc-200 placeholder:text-zinc-500 focus:border-zinc-600 focus:bg-zinc-900 focus:outline-none focus:ring-1 focus:ring-zinc-600 transition-all"
          />
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-3">
        {tab === "examples" && (
          <ExamplesList
            items={props.examples}
            search={search}
            selected={props.selectedExample}
            onSelect={props.onSelectExample}
          />
        )}
        {tab === "saved" && (
          <SavedList
            items={props.saved}
            search={search}
            selected={props.selectedSaved}
            onSelect={props.onSelectSaved}
            onDelete={props.onDeleteSaved}
          />
        )}
        {tab === "boards" && (
          <BoardsList items={props.boards} search={search} onSelect={props.onSelectBoard} />
        )}
        {tab === "components" && (
          <ComponentsList items={props.components} search={search} onSelect={props.onSelectComponent} />
        )}
      </div>
    </aside>
  );
}

function SavedList({
  items, search, selected, onSelect, onDelete,
}: {
  items: SavedDesignSummary[] | null;
  search: string;
  selected: string | null;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  const filtered = useMemo(() => {
    if (!items) return null;
    const q = search.trim().toLowerCase();
    return q ? items.filter((s) => s.id.toLowerCase().includes(q) || s.name.toLowerCase().includes(q)) : items;
  }, [items, search]);

  if (filtered === null) return <Loading />;
  if (filtered.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-8 text-center px-4">
        <FolderHeart className="h-8 w-8 text-zinc-800 mb-3" />
        <p className="text-xs text-zinc-500">No saved designs yet.</p>
        <p className="text-xs text-zinc-600 mt-1">
          Click <span className="font-medium text-zinc-400 bg-zinc-900 px-1 py-0.5 rounded">Save</span> in the header to persist the current design here.
        </p>
      </div>
    );
  }

  return (
    <ul className="space-y-1.5 text-sm">
      {filtered.map((s) => {
        const active = selected === s.id;
        return (
          <li key={s.id} className="flex items-stretch gap-1">
            <button
              onClick={() => onSelect(s.id)}
              className={`flex-1 rounded-md px-3 py-2 text-left transition-all ${
                active
                  ? "bg-blue-500/15 text-blue-100 ring-1 ring-inset ring-blue-500/30"
                  : "bg-zinc-900/30 hover:bg-zinc-800/80"
              }`}
            >
              <div className="flex items-baseline justify-between gap-2">
                <div className={`truncate font-medium ${active ? "text-blue-100" : "text-zinc-200"}`}>
                  {s.name || s.id}
                </div>
                <div className="shrink-0 text-[10px] font-medium text-zinc-500">
                  {relativeTime(s.saved_at)}
                </div>
              </div>
              <div className="mt-1 flex items-center gap-2 truncate text-xs text-zinc-500">
                <span className="shrink-0 font-medium text-zinc-400">{s.chip_family}</span>
                <span className="h-1 w-1 shrink-0 rounded-full bg-zinc-700"></span>
                <span className="truncate">{s.board_library_id}</span>
                <span className="h-1 w-1 shrink-0 rounded-full bg-zinc-700"></span>
                <span className="shrink-0">{s.component_count} comp</span>
              </div>
            </button>
            <button
              onClick={() => {
                if (confirm(`Delete saved design "${s.name || s.id}"?`)) onDelete(s.id);
              }}
              title={`Delete ${s.id}`}
              className={`flex items-center justify-center rounded-md px-2 text-zinc-500 transition-colors hover:bg-red-500/15 hover:text-red-400 ${
                active ? "bg-blue-500/5 hover:bg-red-500/15" : "bg-zinc-900/30"
              }`}
            >
              ✕
            </button>
          </li>
        );
      })}
    </ul>
  );
}

function relativeTime(iso: string): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  const dSec = (Date.now() - t) / 1000;
  if (dSec < 60) return "just now";
  if (dSec < 3600) return `${Math.round(dSec / 60)}m ago`;
  if (dSec < 86400) return `${Math.round(dSec / 3600)}h ago`;
  return `${Math.round(dSec / 86400)}d ago`;
}

function ExamplesList({
  items, search, selected, onSelect,
}: {
  items: ExampleSummary[] | null;
  search: string;
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const filtered = useMemo(() => {
    if (!items) return null;
    const q = search.trim().toLowerCase();
    return q ? items.filter((e) => e.id.toLowerCase().includes(q) || e.name.toLowerCase().includes(q)) : items;
  }, [items, search]);

  if (filtered === null) return <Loading />;
  if (filtered.length === 0) return <Empty>No examples found.</Empty>;

  return (
    <ul className="space-y-1.5 text-sm">
      {filtered.map((e) => {
        const active = selected === e.id;
        return (
          <li key={e.id}>
            <button
              onClick={() => onSelect(e.id)}
              className={`w-full rounded-md px-3 py-2 text-left transition-all ${
                active
                  ? "bg-blue-500/15 text-blue-100 ring-1 ring-inset ring-blue-500/30"
                  : "bg-zinc-900/30 hover:bg-zinc-800/80"
              }`}
            >
              <div className={`truncate font-medium ${active ? "text-blue-100" : "text-zinc-200"}`}>
                {e.name}
              </div>
              <div className="mt-1 flex items-center gap-2 truncate text-xs text-zinc-500">
                <span className="shrink-0 font-medium text-zinc-400">{e.chip_family}</span>
                <span className="h-1 w-1 shrink-0 rounded-full bg-zinc-700"></span>
                <span className="truncate">{e.board_library_id}</span>
              </div>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

function BoardsList({
  items, search, onSelect,
}: {
  items: BoardSummary[] | null;
  search: string;
  onSelect: (id: string) => void;
}) {
  const filtered = useMemo(() => {
    if (!items) return null;
    const q = search.trim().toLowerCase();
    return q ? items.filter((b) => b.id.toLowerCase().includes(q) || b.name.toLowerCase().includes(q)) : items;
  }, [items, search]);

  if (filtered === null) return <Loading />;
  if (filtered.length === 0) return <Empty>No boards found.</Empty>;

  return (
    <ul className="space-y-1.5 text-sm">
      {filtered.map((b) => (
        <li key={b.id}>
          <button
            onClick={() => onSelect(b.id)}
            className="w-full rounded-md bg-zinc-900/30 px-3 py-2 text-left transition-colors hover:bg-zinc-800/80"
          >
            <div className="truncate font-medium text-zinc-200">{b.name}</div>
            <div className="mt-1 flex items-center gap-1.5 truncate text-xs text-zinc-500">
              <span className="rounded bg-zinc-800 px-1 py-0.5 font-medium text-zinc-400">{b.chip_variant}</span>
              <span className="text-zinc-600">·</span>
              <span>{b.framework}</span>
              {b.flash_size_mb && (
                <>
                  <span className="text-zinc-600">·</span>
                  <span>{b.flash_size_mb}MB</span>
                </>
              )}
            </div>
          </button>
        </li>
      ))}
    </ul>
  );
}

function ComponentsList({
  items, search, onSelect,
}: {
  items: ComponentSummary[] | null;
  search: string;
  onSelect: (id: string) => void;
}) {
  const filtered = useMemo(() => {
    if (!items) return null;
    const q = search.trim().toLowerCase();
    return q
      ? items.filter((c) =>
          c.id.toLowerCase().includes(q)
          || c.name.toLowerCase().includes(q)
          || c.category.toLowerCase().includes(q)
          || c.use_cases.some((u) => u.toLowerCase().includes(q))
          || c.aliases.some((a) => a.toLowerCase().includes(q))
        )
      : items;
  }, [items, search]);

  if (filtered === null) return <Loading />;
  if (filtered.length === 0) return <Empty>No components found.</Empty>;

  return (
    <ul className="space-y-1.5 text-sm">
      {filtered.map((c) => (
        <li key={c.id}>
          <button
            onClick={() => onSelect(c.id)}
            className="w-full rounded-md bg-zinc-900/30 px-3 py-2 text-left transition-colors hover:bg-zinc-800/80"
          >
            <div className="flex items-baseline justify-between gap-2">
              <div className="truncate font-medium text-zinc-200">{c.name}</div>
              <div className="shrink-0 text-[10px] font-medium uppercase tracking-wider text-zinc-500">
                {c.category}
              </div>
            </div>
            {c.required_components.length > 0 && (
              <div className="mt-1 truncate text-xs text-zinc-500">
                <span className="text-zinc-600 mr-1">Requires:</span>
                {c.required_components.join(", ")}
              </div>
            )}
          </button>
        </li>
      ))}
    </ul>
  );
}

function Loading() {
  return (
    <div className="flex items-center justify-center py-8 text-xs text-zinc-500">
      <div className="flex items-center gap-2">
        <span className="relative flex h-2 w-2">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-zinc-500 opacity-75"></span>
          <span className="relative inline-flex h-2 w-2 rounded-full bg-zinc-600"></span>
        </span>
        Loading...
      </div>
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-center py-8 text-center text-sm text-zinc-500">
      {children}
    </div>
  );
}
