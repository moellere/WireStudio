/**
 * Provisioning UI for the LoRaWAN external-component path
 * (`lorawan-for-esphome`). The companion of `LorawanFlashDialog`, which is
 * the standalone Arduino path; this one drives the W3 endpoint
 * (`POST /lorawan/provision-esphome`) and surfaces the join status from
 * `GET /lorawan/activation/{dev_eui}`.
 *
 * Minimum viable scope: the user takes a design that already has
 * `target: "esphome"` + `lorawan.payload` set, types in a DevEUI (manual
 * override per the locked decision in docs/lorawan/workflow-integration.md),
 * clicks Provision, gets back a copy-friendly `secrets:` block to drop into
 * the secrets.yaml that rides next to the rendered ESPHome config, and
 * watches the join land. Build + flash are existing flows (PushToFleetDialog
 * for the fleet-for-esphome path) -- this dialog is purely the LoRaWAN
 * orchestration step.
 */
import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import type {
  Design,
  LorawanActivationResponse,
  LorawanProvisionEsphomeResponse,
} from "../types/api";

const ACTIVATION_POLL_INTERVAL_MS = 3000;
const DEV_EUI_RE = /^[0-9a-fA-F]{16}$/;

interface Props {
  design: Design;
  onClose: () => void;
}

/** The bits of `design.lorawan` this dialog reads. Design itself is typed
 *  opaquely (Record<string, unknown>) in api.ts; narrow inline rather than
 *  widening that contract for one consumer. */
interface LorawanBlock {
  region?: string;
  sub_band?: number;
  payload?: { sensor: string }[];
  dev_eui?: string;
}

function readLorawan(design: Design): LorawanBlock | null {
  const v = (design as { lorawan?: unknown }).lorawan;
  if (!v || typeof v !== "object") return null;
  return v as LorawanBlock;
}

function secretsYamlBody(s: LorawanProvisionEsphomeResponse["secrets"]): string {
  return [
    "# LoRaWAN keys for lorawan-for-esphome -- drop next to the rendered",
    "# ESPHome config. The AppKey was minted server-side and is the same",
    "# value registered in ChirpStack. Treat it as a secret.",
    `dev_eui:  "${s.dev_eui}"`,
    `join_eui: "${s.join_eui}"`,
    `app_key:  "${s.app_key}"`,
    "",
  ].join("\n");
}

export function LorawanProvisionEsphomeDialog({ design, onClose }: Props) {
  const lorawan = readLorawan(design);
  const payloadFields = lorawan?.payload ?? [];
  const eligible = (design as { target?: string }).target === "esphome" && payloadFields.length > 0;

  const [devEui, setDevEui] = useState<string>(lorawan?.dev_eui ?? "");
  const [provisioning, setProvisioning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<LorawanProvisionEsphomeResponse | null>(null);
  const [activation, setActivation] = useState<LorawanActivationResponse | null>(null);
  const [activationErr, setActivationErr] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Reset the copy-feedback flag a couple seconds after the user copies, so
  // the button doesn't stay green forever on a multi-paste workflow.
  useEffect(() => {
    if (!copied) return;
    const t = setTimeout(() => setCopied(false), 1800);
    return () => clearTimeout(t);
  }, [copied]);

  // Poll /lorawan/activation/{dev_eui} once provisioning succeeded, until
  // joined=true (then stop) or the dialog closes.
  useEffect(() => {
    if (!result) return;
    const eui = result.secrets.dev_eui;

    let cancelled = false;
    async function tick() {
      try {
        const a = await api.lorawanActivation(eui);
        if (cancelled) return;
        setActivation(a);
        setActivationErr(null);
        if (a.joined && pollRef.current) {
          clearInterval(pollRef.current);
          pollRef.current = null;
        }
      } catch (e) {
        if (cancelled) return;
        setActivationErr(e instanceof Error ? e.message : String(e));
      }
    }
    void tick(); // immediate first read
    pollRef.current = setInterval(tick, ACTIVATION_POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [result]);

  async function handleProvision() {
    setError(null);
    setProvisioning(true);
    setActivation(null);
    setActivationErr(null);
    try {
      const r = await api.lorawanProvisionEsphome({
        dev_eui: devEui,
        design,
      });
      setResult(r);
    } catch (e) {
      let msg: string;
      if (e instanceof ApiError) {
        const detail = (e.body as { detail?: unknown } | undefined)?.detail;
        msg = `${e.status}: ${typeof detail === "string" ? detail : e.message}`;
      } else {
        msg = e instanceof Error ? e.message : String(e);
      }
      setError(msg);
    } finally {
      setProvisioning(false);
    }
  }

  async function handleCopy() {
    if (!result) return;
    const text = secretsYamlBody(result.secrets);
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
    } catch {
      // Clipboard API can be blocked (insecure context, missing permission);
      // selecting the textarea below is the manual fallback.
      setCopied(false);
    }
  }

  const devEuiValid = DEV_EUI_RE.test(devEui);
  const canProvision = eligible && devEuiValid && !provisioning && !result;

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
            <div className="text-sm font-semibold text-zinc-100">Provision LoRaWAN device</div>
            <div className="text-xs text-zinc-500">
              Mint keys in ChirpStack for the lorawan-for-esphome external-component path.
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-md border border-zinc-800 px-2 py-1 text-xs text-zinc-300 hover:bg-zinc-900"
          >
            Close
          </button>
        </div>

        <div className="space-y-4 p-4 text-sm">
          {/* Eligibility / context */}
          <div className="rounded-md border border-zinc-800 bg-zinc-900/40 p-3">
            <div className="text-[11px] uppercase tracking-wide text-zinc-500">design</div>
            <div className="mt-1 text-xs text-zinc-200">
              <span className="text-zinc-300">{String((design as { name?: string }).name ?? "")}</span>{" "}
              <span className="text-zinc-500">({String((design as { id?: string }).id ?? "")})</span>
            </div>
            {!eligible ? (
              <div className="mt-2 text-xs text-amber-300">
                This design isn't eligible for the external-component path. Set{" "}
                <code className="rounded-md bg-zinc-800 px-1">target: "esphome"</code> and add at
                least one entry to{" "}
                <code className="rounded-md bg-zinc-800 px-1">lorawan.payload</code>, then reopen
                this dialog. The standalone Arduino path uses{" "}
                <em>Flash LoRaWAN firmware</em> instead.
              </div>
            ) : (
              <div className="mt-2 space-y-1 text-xs text-zinc-400">
                <div>
                  Payload fields:{" "}
                  <span className="text-zinc-200">
                    {payloadFields.map((f) => f.sensor).join(", ")}
                  </span>
                </div>
                <div>
                  Band:{" "}
                  <span className="text-zinc-200">
                    {lorawan?.region ?? "US915"} sub-band {lorawan?.sub_band ?? 2}
                  </span>
                </div>
              </div>
            )}
          </div>

          {/* DevEUI input */}
          {eligible && (
            <div className="space-y-1">
              <label className="block text-[11px] uppercase tracking-wide text-zinc-500">
                DevEUI (16 hex chars)
              </label>
              <input
                type="text"
                value={devEui}
                onChange={(e) => setDevEui(e.target.value)}
                disabled={!!result}
                placeholder="70b3d57ed0001234"
                className="w-full rounded-md border border-zinc-800 bg-black/40 px-2 py-1.5 font-mono text-xs text-zinc-100 placeholder:text-zinc-600 focus:border-zinc-600 focus:outline-none disabled:opacity-60"
              />
              <div className="text-[11px] text-zinc-500">
                Manual override per the locked decision. MAC-derivation from the chip's eFuse over
                WebSerial lands in a follow-up.
              </div>
              {!devEuiValid && devEui.length > 0 && (
                <div className="text-[11px] text-amber-400">
                  Expected 16 hex characters; got {devEui.length}.
                </div>
              )}
            </div>
          )}

          {error && (
            <div className="rounded-md border border-rose-700/50 bg-rose-900/20 px-3 py-2 text-xs text-rose-200">
              {error}
            </div>
          )}

          {/* Provisioned secrets */}
          {result && (
            <div className="space-y-2 rounded-md border border-emerald-700/50 bg-emerald-900/20 p-3">
              <div className="flex items-center justify-between">
                <div className="text-[11px] uppercase tracking-wide text-emerald-300">
                  provisioned
                </div>
                <div className="text-[11px] text-emerald-300/80">
                  app: <code>{result.chirpstack.application_id}</code> · profile:{" "}
                  <code>{result.chirpstack.device_profile_id}</code>
                </div>
              </div>
              <textarea
                readOnly
                value={secretsYamlBody(result.secrets)}
                onClick={(e) => (e.target as HTMLTextAreaElement).select()}
                rows={6}
                className="w-full rounded-md border border-emerald-800/40 bg-black/60 px-2 py-1.5 font-mono text-[11px] leading-relaxed text-emerald-100/90 focus:outline-none"
              />
              <div className="flex items-center justify-between text-[11px]">
                <div className="text-emerald-200/80">
                  Drop these alongside the rendered ESPHome YAML as{" "}
                  <code className="rounded-md bg-emerald-900/40 px-1">secrets.yaml</code>. The
                  AppKey is shown once.
                </div>
                <button
                  onClick={handleCopy}
                  className="rounded-md border border-emerald-700/60 bg-emerald-900/40 px-2 py-1 text-[11px] text-emerald-100 hover:bg-emerald-900/60"
                >
                  {copied ? "Copied" : "Copy"}
                </button>
              </div>
            </div>
          )}

          {/* Activation poll */}
          {result && (
            <div className="rounded-md border border-zinc-800 bg-zinc-900/40 p-3">
              <div className="text-[11px] uppercase tracking-wide text-zinc-500">
                join status
              </div>
              {activationErr ? (
                <div className="mt-1 text-xs text-rose-400">error: {activationErr}</div>
              ) : activation === null ? (
                <div className="mt-1 text-xs text-zinc-500">polling ChirpStack…</div>
              ) : activation.joined ? (
                <div className="mt-1 space-y-1 text-xs">
                  <div className="text-emerald-400">
                    joined · dev_addr <code>{activation.dev_addr}</code>
                  </div>
                  {typeof activation.f_cnt_up === "number" && (
                    <div className="text-zinc-500">uplink frames: {activation.f_cnt_up}</div>
                  )}
                </div>
              ) : (
                <div className="mt-1 text-xs text-amber-300">
                  waiting for OTAA join… (build + flash the firmware, then check back)
                </div>
              )}
            </div>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <button
              onClick={onClose}
              className="rounded-md border border-zinc-800 px-2 py-1 text-xs text-zinc-300 hover:bg-zinc-900"
            >
              {result ? "Done" : "Cancel"}
            </button>
            {!result && eligible && (
              <button
                disabled={!canProvision}
                onClick={handleProvision}
                className="rounded-md bg-blue-500/20 px-3 py-1.5 text-sm text-blue-100 ring-1 ring-blue-400/40 enabled:hover:bg-blue-500/30 disabled:opacity-40"
              >
                {provisioning ? "Provisioning…" : "Provision →"}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
