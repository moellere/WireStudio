import { useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import type { Design, FleetPushResponse, FleetStatus } from "../types/api";

interface Props {
  design: Design;
  onClose: () => void;
}

/**
 * "Push to fleet" modal. Renders the current design's YAML and POSTs it to
 * the distributed-esphome ha-addon configured via FLEET_URL/FLEET_TOKEN on
 * the studio API. The user can optionally enqueue a compile in the same
 * round-trip.
 *
 * Status is fetched on open so we can disable the button + show why the
 * fleet isn't reachable when it isn't.
 */
export function PushToFleetDialog({ design, onClose }: Props) {
  const [status, setStatus] = useState<FleetStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const fleet = (design.fleet as Record<string, unknown> | undefined) ?? undefined;
  const fleetDeviceName = typeof fleet?.device_name === "string" ? fleet.device_name : "";
  const designId = typeof design.id === "string" ? design.id : "";
  const [deviceName, setDeviceName] = useState<string>(fleetDeviceName || designId);
  const [compile, setCompile] = useState<boolean>(false);
  const [pushing, setPushing] = useState(false);
  const [result, setResult] = useState<FleetPushResponse | null>(null);
  const [pushError, setPushError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const s = await api.fleetStatus();
        if (!cancelled) setStatus(s);
      } catch (e) {
        if (cancelled) return;
        const msg = e instanceof ApiError ? `${e.status}: ${e.message}` :
          e instanceof Error ? e.message : String(e);
        setStatusError(msg);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  async function handlePush() {
    setPushing(true);
    setPushError(null);
    setResult(null);
    try {
      const r = await api.fleetPush({
        design,
        compile,
        device_name: deviceName.trim() || undefined,
      });
      setResult(r);
    } catch (e) {
      const msg = e instanceof ApiError
        ? `${e.status}: ${typeof e.body === "object" && e.body && "detail" in e.body
            ? String((e.body as { detail: unknown }).detail) : e.message}`
        : e instanceof Error ? e.message : String(e);
      setPushError(msg);
    } finally {
      setPushing(false);
    }
  }

  const canPush = !pushing && status?.available && deviceName.trim().length > 0;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="m-4 max-h-[85vh] w-full max-w-xl overflow-hidden rounded-lg border border-zinc-800 bg-zinc-950 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-3">
          <div>
            <div className="text-sm font-semibold text-zinc-100">Push to fleet</div>
            <div className="text-xs text-zinc-500">
              Send the rendered YAML to distributed-esphome (ha-addon).
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded border border-zinc-800 px-2 py-1 text-xs text-zinc-300 hover:bg-zinc-900"
          >
            Close
          </button>
        </div>

        <div className="space-y-4 p-4 text-sm">
          {/* Status section */}
          <div className="rounded border border-zinc-800 bg-zinc-900/40 p-3">
            <div className="text-[11px] uppercase tracking-wide text-zinc-500">fleet status</div>
            {statusError ? (
              <div className="mt-1 text-xs text-rose-400">error: {statusError}</div>
            ) : status === null ? (
              <div className="mt-1 text-xs text-zinc-500">checking…</div>
            ) : status.available ? (
              <div className="mt-1 text-xs text-emerald-400">
                connected · {status.url || "fleet"}
              </div>
            ) : (
              <div className="mt-1 space-y-1 text-xs">
                <div className="text-amber-300">unavailable: {status.reason || "unknown"}</div>
                <div className="text-zinc-500">
                  Set <code className="rounded bg-zinc-800 px-1">FLEET_URL</code> and{" "}
                  <code className="rounded bg-zinc-800 px-1">FLEET_TOKEN</code> in the API server's
                  environment, then restart it.
                </div>
              </div>
            )}
          </div>

          <div className="space-y-1">
            <label className="block text-[11px] uppercase tracking-wide text-zinc-500">
              device name
            </label>
            <input
              type="text"
              value={deviceName}
              onChange={(e) =>
                setDeviceName(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, "-"))
              }
              placeholder="garage-motion"
              className="w-full rounded border border-zinc-800 bg-zinc-900 px-2 py-1.5 font-mono text-xs text-zinc-100 focus:border-zinc-600 focus:outline-none"
            />
            <p className="text-[11px] text-zinc-500">
              Will be saved on the fleet as <code>{deviceName.trim() || "<name>"}.yaml</code>.
              Lowercase letters, digits, and hyphens only (max 64).
            </p>
          </div>

          <label className="flex cursor-pointer items-start gap-2 rounded border border-zinc-800 bg-zinc-900/40 px-3 py-2">
            <input
              type="checkbox"
              checked={compile}
              onChange={(e) => setCompile(e.target.checked)}
              className="mt-0.5 h-3.5 w-3.5"
            />
            <span className="text-xs">
              <span className="text-zinc-100">Compile after upload</span>
              <span className="ml-2 text-zinc-500">
                Enqueues an OTA build for this device on the fleet.
              </span>
            </span>
          </label>

          {pushError && (
            <div className="rounded border border-rose-700/50 bg-rose-900/20 px-3 py-2 text-xs text-rose-200">
              {pushError}
            </div>
          )}

          {result && (
            <div className="rounded border border-emerald-700/50 bg-emerald-900/20 px-3 py-2 text-xs text-emerald-100">
              <div>
                {result.created ? "Created" : "Updated"}{" "}
                <code className="rounded bg-emerald-900/40 px-1">{result.filename}</code> on the fleet.
              </div>
              {result.run_id && (
                <div className="mt-1 text-emerald-200/80">
                  Compile enqueued: <code>{result.run_id}</code>
                  {result.enqueued ? ` (${result.enqueued} job)` : ""}.
                </div>
              )}
            </div>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <button
              onClick={onClose}
              className="rounded border border-zinc-800 px-2 py-1 text-xs text-zinc-300 hover:bg-zinc-900"
            >
              {result ? "Done" : "Cancel"}
            </button>
            <button
              disabled={!canPush}
              onClick={handlePush}
              className="rounded bg-blue-500/20 px-3 py-1.5 text-sm text-blue-100 ring-1 ring-blue-400/40 enabled:hover:bg-blue-500/30 disabled:opacity-40"
            >
              {pushing ? "Pushing…" : compile ? "Push & compile →" : "Push →"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
