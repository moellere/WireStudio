/**
 * Schematic export dialog (0.9). Downloads a SKiDL Python script the
 * user runs locally to produce `<design_id>.kicad_sch`. The studio
 * doesn't import or run SKiDL itself -- this keeps the generated
 * artefact transparent (the user can `cat` it, edit it, regenerate)
 * and avoids adding numpy + an EDA toolchain to the server.
 */
import { useState } from "react";
import { api, ApiError } from "../api/client";
import type { Design } from "../types/api";

interface Props {
  design: Design;
  onClose: () => void;
}

export function SchematicDialog({ design, onClose }: Props) {
  const [downloading, setDownloading] = useState(false);
  const [downloaded, setDownloaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleDownload() {
    setDownloading(true);
    setDownloaded(false);
    setError(null);
    try {
      const py = await api.kicadSchematic(design);
      const blob = new Blob([py], { type: "text/x-python" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${design.id ?? "design"}.skidl.py`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      setDownloaded(true);
    } catch (e) {
      let msg: string;
      if (e instanceof ApiError) {
        const body = e.body as { detail?: unknown } | undefined;
        const detail = body?.detail;
        msg = `${e.status}: ${typeof detail === "string" ? detail : e.message}`;
      } else {
        msg = e instanceof Error ? e.message : String(e);
      }
      setError(msg);
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="m-4 flex max-h-[85vh] w-full max-w-xl flex-col overflow-hidden rounded-lg border border-zinc-800 bg-zinc-950 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-3">
          <div>
            <div className="text-sm font-semibold text-zinc-100">KiCad schematic</div>
            <div className="text-xs text-zinc-500">
              SKiDL Python script — run locally to produce a `.kicad_sch`.
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded border border-zinc-800 px-2 py-1 text-xs text-zinc-300 hover:bg-zinc-900"
          >
            Close
          </button>
        </div>

        <div className="space-y-3 p-4 text-sm text-zinc-300">
          <p className="text-xs leading-relaxed text-zinc-400">
            Downloads a self-contained <code className="text-zinc-200">.skidl.py</code>
            file. Run it with{" "}
            <a
              href="https://devbisme.github.io/skidl/"
              target="_blank"
              rel="noreferrer noopener"
              className="text-blue-300 hover:underline"
            >
              SKiDL
            </a>
            {" "}installed:
          </p>
          <pre className="overflow-x-auto rounded border border-zinc-800 bg-black/60 p-2 font-mono text-[11px] leading-relaxed text-zinc-200">
{`pip install skidl
python ${design.id ?? "design"}.skidl.py
# produces ${design.id ?? "design"}.kicad_sch in the cwd`}
          </pre>
          <p className="text-[11px] text-zinc-500">
            Components without a <code>kicad:</code> mapping in the studio
            library render as a generic 4-pin connector with a TODO
            comment; you can either patch the .py before running or fill
            in the library YAML and re-export. Pin-name remaps from
            each component's <code>kicad.pin_map</code> are baked into
            the script (e.g., the BME280's VCC role becomes VDD on the
            schematic to match the Bosch symbol's pin name).
          </p>
          <button
            onClick={handleDownload}
            disabled={downloading}
            className="rounded bg-blue-500/20 px-3 py-1.5 text-sm text-blue-100 ring-1 ring-blue-400/40 enabled:hover:bg-blue-500/30 disabled:opacity-40"
          >
            {downloading
              ? "Generating…"
              : downloaded
                ? "Downloaded ✓ — generate again"
                : "Download .skidl.py →"}
          </button>
          {error && (
            <div className="rounded border border-rose-700/40 bg-rose-900/15 px-2 py-1.5 text-xs text-rose-200">
              {error}
            </div>
          )}
          <p className="text-[11px] text-zinc-500">
            PCB layout (Freerouting + Gerber export) is on the 1.0+
            roadmap; for now the netlist + schematic are sufficient to
            open in KiCad and start a layout by hand.
          </p>
        </div>
      </div>
    </div>
  );
}
