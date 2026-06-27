import { useEffect, useState } from "react";
import { Check, Copy, Eye, EyeOff, KeyRound, RotateCcw } from "lucide-react";
import { ApiError, api, type McpTokenInfo } from "../api/client";

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; info: McpTokenInfo }
  | { kind: "absent" } // server built without MCP
  | { kind: "error"; message: string };

function errMessage(e: unknown): string {
  if (e instanceof ApiError) {
    const detail = (e.body as { detail?: unknown } | undefined)?.detail;
    return `${e.status}: ${typeof detail === "string" ? detail : e.message}`;
  }
  return e instanceof Error ? e.message : String(e);
}

export function SettingsDialog({ onClose }: { onClose: () => void }) {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [revealed, setRevealed] = useState(false);
  const [copied, setCopied] = useState(false);
  const [confirmRotate, setConfirmRotate] = useState(false);
  const [rotating, setRotating] = useState(false);
  const [rotateError, setRotateError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api
      .mcpToken()
      .then((info) => live && setState({ kind: "ready", info }))
      .catch((e) => {
        if (!live) return;
        if (e instanceof ApiError && e.status === 404) setState({ kind: "absent" });
        else setState({ kind: "error", message: errMessage(e) });
      });
    return () => {
      live = false;
    };
  }, []);

  const token = state.kind === "ready" ? state.info.token : "";
  const envManaged = state.kind === "ready" && state.info.managed === "env";

  async function copyToken() {
    try {
      await navigator.clipboard.writeText(token);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked; user can reveal + copy manually */
    }
  }

  async function rotate() {
    setRotating(true);
    setRotateError(null);
    try {
      const info = await api.mcpTokenRotate();
      setState({ kind: "ready", info });
      setRevealed(true);
      setConfirmRotate(false);
    } catch (e) {
      setRotateError(errMessage(e));
    } finally {
      setRotating(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="m-4 max-h-[85vh] w-full max-w-xl overflow-y-auto rounded-lg border border-zinc-800 bg-zinc-950 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-3">
          <div>
            <div className="text-sm font-semibold text-zinc-100">Settings</div>
            <div className="text-xs text-zinc-500">Connection and access for external clients.</div>
          </div>
          <button
            onClick={onClose}
            className="rounded-md border border-zinc-800 px-2 py-1 text-xs text-zinc-300 hover:bg-zinc-900"
          >
            Close
          </button>
        </div>

        <div className="space-y-4 p-4 text-sm">
          <section className="rounded-md border border-zinc-800 bg-zinc-900/40 p-3">
            <div className="flex items-center gap-2">
              <KeyRound className="h-4 w-4 text-zinc-400" />
              <span className="text-[11px] uppercase tracking-wide text-zinc-500">
                MCP bearer token
              </span>
            </div>
            <p className="mt-1 text-xs text-zinc-400">
              MCP clients (Claude Desktop, Claude Code) authenticate to the <code className="rounded bg-zinc-800 px-1">/mcp</code>{" "}
              endpoint with this token via an <code className="rounded bg-zinc-800 px-1">Authorization: Bearer …</code> header.
            </p>

            {state.kind === "loading" && (
              <div className="mt-3 text-xs text-zinc-500">Loading…</div>
            )}

            {state.kind === "absent" && (
              <div className="mt-3 text-xs text-amber-300">
                This server was built without the MCP endpoint, so there is no token.
              </div>
            )}

            {state.kind === "error" && (
              <div className="mt-3 text-xs text-rose-400">Couldn't load token — {state.message}</div>
            )}

            {state.kind === "ready" && (
              <>
                <div className="mt-3 flex items-stretch gap-2">
                  <input
                    readOnly
                    value={revealed ? token : "•".repeat(Math.min(token.length, 44))}
                    className="flex-1 rounded-md border border-zinc-800 bg-zinc-950 px-2 py-1.5 font-mono text-xs text-zinc-200"
                  />
                  <button
                    onClick={() => setRevealed((r) => !r)}
                    title={revealed ? "Hide" : "Reveal"}
                    className="rounded-md border border-zinc-800 px-2 text-zinc-300 hover:bg-zinc-900"
                  >
                    {revealed ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                  <button
                    onClick={copyToken}
                    title="Copy"
                    className="flex items-center gap-1 rounded-md border border-zinc-800 px-2 text-xs text-zinc-300 hover:bg-zinc-900"
                  >
                    {copied ? <Check className="h-4 w-4 text-emerald-400" /> : <Copy className="h-4 w-4" />}
                  </button>
                </div>

                {envManaged ? (
                  <div className="mt-3 text-xs text-zinc-400">
                    This token is set via the <code className="rounded bg-zinc-800 px-1">WIRESTUDIO_MCP_TOKEN</code>{" "}
                    environment variable, so it's read-only here. Rotate it by updating that secret and
                    restarting the server.
                  </div>
                ) : (
                  <div className="mt-3">
                    {!confirmRotate ? (
                      <button
                        onClick={() => {
                          setConfirmRotate(true);
                          setRotateError(null);
                        }}
                        className="flex items-center gap-1.5 rounded-md border border-zinc-800 px-2.5 py-1.5 text-xs text-zinc-300 hover:bg-zinc-900"
                      >
                        <RotateCcw className="h-4 w-4" />
                        Regenerate token
                      </button>
                    ) : (
                      <div className="rounded-md border border-amber-900/60 bg-amber-950/30 p-3">
                        <div className="text-xs text-amber-200">
                          Regenerating immediately invalidates the current token. Any connected MCP
                          client will get 401s until you update it with the new value.
                        </div>
                        <div className="mt-2 flex gap-2">
                          <button
                            onClick={rotate}
                            disabled={rotating}
                            className="rounded-md border border-amber-700 bg-amber-900/40 px-2.5 py-1 text-xs text-amber-100 hover:bg-amber-900/70 disabled:opacity-50"
                          >
                            {rotating ? "Regenerating…" : "Confirm regenerate"}
                          </button>
                          <button
                            onClick={() => setConfirmRotate(false)}
                            disabled={rotating}
                            className="rounded-md border border-zinc-800 px-2.5 py-1 text-xs text-zinc-300 hover:bg-zinc-900 disabled:opacity-50"
                          >
                            Cancel
                          </button>
                        </div>
                      </div>
                    )}
                    {rotateError && (
                      <div className="mt-2 text-xs text-rose-400">{rotateError}</div>
                    )}
                  </div>
                )}
              </>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
