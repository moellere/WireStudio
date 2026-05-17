import { useState } from "react";
import { Copy, Check } from "lucide-react";
import type { Design, RenderResponse } from "../types/api";
import { Loading } from "./Status";

type Tab = "ascii" | "yaml" | "json";

interface Props {
  design: Design | null;
  render: RenderResponse | null;
  renderError: string | null;
}

export function DesignPane({ design, render, renderError }: Props) {
  const [tab, setTab] = useState<Tab>("ascii");
  const [copied, setCopied] = useState(false);

  const meta = design ? readMeta(design) : null;

  const content =
    tab === "json"
      ? design
        ? JSON.stringify(design, null, 2)
        : ""
      : tab === "yaml"
        ? render?.yaml ?? ""
        : render?.ascii ?? "";

  async function copy() {
    if (!content) return;
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard blocked (insecure context / permissions) -- no-op
    }
  }

  return (
    <section className="flex min-h-0 flex-col">
      <div className="border-b border-zinc-800 px-4 py-3">
        {meta ? (
          <>
            <div className="flex items-baseline gap-2">
              <h2 className="text-base font-semibold tracking-tight">{meta.name}</h2>
              <code className="text-xs text-zinc-500">{meta.id}</code>
            </div>
            {meta.description && (
              <p className="mt-1 max-w-prose text-sm text-zinc-400">{meta.description}</p>
            )}
            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-zinc-500">
              <span>board: <code className="text-zinc-300">{meta.boardId}</code></span>
              <span>mcu: <code className="text-zinc-300">{meta.mcu}</code></span>
              {meta.framework && <span>framework: <code className="text-zinc-300">{meta.framework}</code></span>}
              <span>{meta.componentCount} components</span>
              <span>{meta.busCount} buses</span>
              <span>{meta.connectionCount} connections</span>
            </div>
          </>
        ) : (
          <div className="text-sm text-zinc-500">No design loaded.</div>
        )}
      </div>

      <div className="flex items-center justify-between border-b border-zinc-800 pr-2 text-xs">
        <div className="flex">
          {(["ascii", "yaml", "json"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-3 py-2 uppercase tracking-wide transition-colors ${
                tab === t
                  ? "border-b-2 border-blue-400 text-zinc-100"
                  : "border-b-2 border-transparent text-zinc-500 hover:text-zinc-300"
              }`}
            >
              {t}
            </button>
          ))}
        </div>
        <button
          onClick={copy}
          disabled={!content}
          title={`Copy the ${tab.toUpperCase()} to the clipboard`}
          className="flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium text-zinc-400 transition-colors enabled:hover:bg-zinc-800 enabled:hover:text-zinc-200 disabled:opacity-40"
        >
          {copied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-auto p-4 font-mono text-[13px] leading-snug">
        {renderError && (
          <div className="mb-3 rounded-md border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-200">
            <div className="font-semibold">Render failed</div>
            <div className="mt-1 whitespace-pre-wrap text-xs">{renderError}</div>
          </div>
        )}

        {!design ? (
          <div className="flex h-full items-center justify-center text-center text-sm text-zinc-600">
            Pick an example or board to start a design.
          </div>
        ) : content ? (
          <pre className="whitespace-pre text-zinc-200">{content}</pre>
        ) : (
          <Loading />
        )}
      </div>
    </section>
  );
}

interface DesignMeta {
  id: string;
  name: string;
  description: string;
  boardId: string;
  mcu: string;
  framework: string | null;
  componentCount: number;
  busCount: number;
  connectionCount: number;
}

function readMeta(d: Design): DesignMeta {
  const board = (d.board ?? {}) as Record<string, unknown>;
  const components = Array.isArray(d.components) ? d.components : [];
  const buses = Array.isArray(d.buses) ? d.buses : [];
  const connections = Array.isArray(d.connections) ? d.connections : [];
  return {
    id: String(d.id ?? ""),
    name: String(d.name ?? ""),
    description: String(d.description ?? ""),
    boardId: String(board.library_id ?? ""),
    mcu: String(board.mcu ?? ""),
    framework: board.framework ? String(board.framework) : null,
    componentCount: components.length,
    busCount: buses.length,
    connectionCount: connections.length,
  };
}
