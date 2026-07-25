import { useEffect, useState } from "react";
import { Check, Copy, Eye, EyeOff, KeyRound, RotateCcw } from "lucide-react";
import { ApiError, api, type McpTokenInfo } from "../api/client";
import { Button, Dialog } from "./ui";

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
    <Dialog
      title="Settings"
      subtitle="Connection and access for external clients."
      onClose={onClose}
      maxWidth="max-w-xl"
    >
      <div className="space-y-4 text-sm">
        <section className="rounded-md border border-line bg-surface-2/40 p-3">
          <div className="flex items-center gap-2">
            <KeyRound className="h-4 w-4 text-ink-dim" />
            <span className="text-[11px] uppercase tracking-wider text-ink-faint">
              MCP bearer token
            </span>
          </div>
          <p className="mt-1 text-xs text-ink-dim">
            MCP clients (Claude Desktop, Claude Code) authenticate to the <code className="rounded bg-surface-2 px-1">/mcp</code>{" "}
            endpoint with this token via an <code className="rounded bg-surface-2 px-1">Authorization: Bearer …</code> header.
          </p>

          {state.kind === "loading" && (
            <div className="mt-3 text-xs text-ink-faint">Loading…</div>
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
                  className="flex-1 rounded-md border border-line bg-surface-1 px-2 py-1.5 font-mono text-xs text-ink"
                />
                <button
                  onClick={() => setRevealed((r) => !r)}
                  title={revealed ? "Hide" : "Reveal"}
                  className="rounded-md border border-line px-2 text-ink-dim transition-colors hover:bg-surface-2 hover:text-ink"
                >
                  {revealed ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
                <button
                  onClick={copyToken}
                  title="Copy"
                  className="flex items-center gap-1 rounded-md border border-line px-2 text-xs text-ink-dim transition-colors hover:bg-surface-2 hover:text-ink"
                >
                  {copied ? <Check className="h-4 w-4 text-emerald-400" /> : <Copy className="h-4 w-4" />}
                </button>
              </div>

              {envManaged ? (
                <div className="mt-3 text-xs text-ink-dim">
                  This token is set via the <code className="rounded bg-surface-2 px-1">WIRESTUDIO_MCP_TOKEN</code>{" "}
                  environment variable, so it's read-only here. Rotate it by updating that secret and
                  restarting the server.
                </div>
              ) : (
                <div className="mt-3">
                  {!confirmRotate ? (
                    <Button
                      onClick={() => {
                        setConfirmRotate(true);
                        setRotateError(null);
                      }}
                    >
                      <RotateCcw className="h-4 w-4" />
                      Regenerate token
                    </Button>
                  ) : (
                    <div className="rounded-md bg-amber-500/10 p-3 ring-1 ring-amber-500/30">
                      <div className="text-xs text-amber-200">
                        Regenerating immediately invalidates the current token. Any connected MCP
                        client will get 401s until you update it with the new value.
                      </div>
                      <div className="mt-2 flex gap-2">
                        <button
                          onClick={rotate}
                          disabled={rotating}
                          className="rounded-md bg-amber-500/15 px-2.5 py-1 text-xs text-amber-100 ring-1 ring-inset ring-amber-500/40 enabled:hover:bg-amber-500/25 disabled:opacity-50"
                        >
                          {rotating ? "Regenerating…" : "Confirm regenerate"}
                        </button>
                        <Button size="sm" onClick={() => setConfirmRotate(false)} disabled={rotating}>
                          Cancel
                        </Button>
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
    </Dialog>
  );
}
