import { useMemo, useState } from "react";
import type { BoardSummary, ComponentSummary, ExampleSummary } from "../types/api";

type Tab = "examples" | "boards" | "components";

interface Props {
  examples: ExampleSummary[] | null;
  boards: BoardSummary[] | null;
  components: ComponentSummary[] | null;
  selectedExample: string | null;
  onSelectExample: (id: string) => void;
  onSelectBoard: (id: string) => void;
  onSelectComponent: (id: string) => void;
}

export function LeftSidebar(props: Props) {
  const [tab, setTab] = useState<Tab>("examples");
  const [search, setSearch] = useState("");

  return (
    <aside className="flex min-h-0 flex-col border-r border-zinc-800">
      <div className="flex border-b border-zinc-800 text-xs">
        {(["examples", "boards", "components"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`flex-1 px-2 py-2 capitalize transition-colors ${
              tab === t
                ? "bg-zinc-900 text-zinc-100"
                : "text-zinc-500 hover:bg-zinc-900/50 hover:text-zinc-300"
            }`}
          >
            {t}
          </button>
        ))}
      </div>
      <input
        type="search"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder={`Filter ${tab}...`}
        className="m-2 rounded border border-zinc-800 bg-zinc-950 px-2 py-1 text-sm text-zinc-200 placeholder:text-zinc-600 focus:border-zinc-600 focus:outline-none"
      />
      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        {tab === "examples" && (
          <ExamplesList
            items={props.examples}
            search={search}
            selected={props.selectedExample}
            onSelect={props.onSelectExample}
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
  if (filtered.length === 0) return <Empty>no examples</Empty>;

  return (
    <ul className="space-y-1 text-sm">
      {filtered.map((e) => {
        const active = selected === e.id;
        return (
          <li key={e.id}>
            <button
              onClick={() => onSelect(e.id)}
              className={`w-full rounded px-2 py-1.5 text-left transition-colors ${
                active
                  ? "bg-blue-500/15 text-blue-100 ring-1 ring-blue-400/40"
                  : "hover:bg-zinc-900"
              }`}
            >
              <div className="truncate font-medium">{e.name}</div>
              <div className="mt-0.5 truncate text-xs text-zinc-500">
                {e.chip_family} · {e.board_library_id}
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
  if (filtered.length === 0) return <Empty>no boards</Empty>;

  return (
    <ul className="space-y-1 text-sm">
      {filtered.map((b) => (
        <li key={b.id}>
          <button
            onClick={() => onSelect(b.id)}
            className="w-full rounded px-2 py-1.5 text-left transition-colors hover:bg-zinc-900"
          >
            <div className="truncate font-medium">{b.name}</div>
            <div className="mt-0.5 truncate text-xs text-zinc-500">
              {b.chip_variant} · {b.framework}
              {b.flash_size_mb ? ` · ${b.flash_size_mb}MB` : ""}
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
  if (filtered.length === 0) return <Empty>no components</Empty>;

  return (
    <ul className="space-y-1 text-sm">
      {filtered.map((c) => (
        <li key={c.id}>
          <button
            onClick={() => onSelect(c.id)}
            className="w-full rounded px-2 py-1.5 text-left transition-colors hover:bg-zinc-900"
          >
            <div className="truncate font-medium">{c.name}</div>
            <div className="mt-0.5 truncate text-xs text-zinc-500">
              {c.category}
              {c.required_components.length ? ` · ${c.required_components.join(", ")}` : ""}
            </div>
          </button>
        </li>
      ))}
    </ul>
  );
}

function Loading() {
  return <div className="px-2 py-3 text-xs text-zinc-500">loading...</div>;
}
function Empty({ children }: { children: React.ReactNode }) {
  return <div className="px-2 py-3 text-xs text-zinc-500">{children}</div>;
}
