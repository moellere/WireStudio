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
  ChirpstackStatus,
  Design,
  LorawanActivationResponse,
  LorawanProvisionEsphomeResponse,
} from "../types/api";
import { detectChip, isWebSerialSupported } from "../lib/usb-detect";
import { macToEui64 } from "../lib/provision";
import { Button, Dialog } from "./ui";

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
  const [detecting, setDetecting] = useState(false);
  const [detected, setDetected] = useState<{ chipName: string; mac: string } | null>(null);
  const [detectErr, setDetectErr] = useState<string | null>(null);
  const [chirpStatus, setChirpStatus] = useState<ChirpstackStatus | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const webSerial = isWebSerialSupported() === "yes";

  // Probe ChirpStack reachability + auth on mount so a misconfigured server
  // (bad token, unreachable, no tenant) is flagged inline instead of after a
  // Provision click that 502s. Failure here disables the Provision button --
  // there's nothing useful to do when ChirpStack is unreachable, and prior
  // behaviour was to let the click through and surface a bare 500.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const s = await api.lorawanChirpstackStatus();
        if (!cancelled) setChirpStatus(s);
      } catch (e) {
        if (cancelled) return;
        // The endpoint itself failed (network, not configured). Surface as
        // unavailable so the Provision button stays disabled.
        setChirpStatus({
          available: false,
          url: null,
          reason: e instanceof Error ? e.message : String(e),
        });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

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

  async function handleDetect() {
    setDetectErr(null);
    setDetected(null);
    setDetecting(true);
    try {
      // detectChip() triggers the WebSerial port-picker, runs esptool-js's
      // sync, reads the eFuse MAC, then disconnects. The chip name + MAC come
      // back; macToEui64 derives a stable EUI-64 from the MAC-48 by inserting
      // 0xFFFE in the middle (standard IEEE mapping).
      const chip = await detectChip();
      if (!chip.mac) {
        throw new Error(
          "chip detected but no MAC available -- try unplugging/reconnecting, or enter the DevEUI manually",
        );
      }
      const eui = macToEui64(chip.mac);
      setDetected({ chipName: chip.chipName, mac: chip.mac });
      setDevEui(eui);
    } catch (e) {
      setDetectErr(e instanceof Error ? e.message : String(e));
    } finally {
      setDetecting(false);
    }
  }

  // "Push to fleet" wires the secrets returned by /lorawan/provision-esphome
  // through to /fleet/push so the rendered YAML the fleet stores carries
  // them inline -- skipping the manual "edit fleet's secrets.yaml" step.
  // State machine: idle -> pushing -> pushed | error. Independent of the
  // activation poll so the user can fire the push and watch the join in
  // parallel.
  type PushState =
    | { kind: "idle" }
    | { kind: "pushing" }
    | { kind: "pushed"; filename: string; created: boolean; run_id: string | null }
    | { kind: "error"; message: string };
  const [pushState, setPushState] = useState<PushState>({ kind: "idle" });

  async function handlePushToFleet() {
    if (!result) return;
    setPushState({ kind: "pushing" });
    try {
      const r = await api.fleetPush({
        design,
        compile: true,
        lorawan_secrets: {
          dev_eui: result.secrets.dev_eui,
          join_eui: result.secrets.join_eui,
          app_key: result.secrets.app_key,
        },
      });
      setPushState({
        kind: "pushed",
        filename: r.filename,
        created: r.created,
        run_id: r.run_id ?? null,
      });
    } catch (e) {
      let msg: string;
      if (e instanceof ApiError) {
        const detail = (e.body as { detail?: unknown } | undefined)?.detail;
        msg = `${e.status}: ${typeof detail === "string" ? detail : e.message}`;
      } else {
        msg = e instanceof Error ? e.message : String(e);
      }
      setPushState({ kind: "error", message: msg });
    }
  }

  // "Flash via WebSerial" picks up the fleet-built factory image (via the
  // studio's /fleet/jobs/{run_id}/firmware passthrough -- browser never sees
  // FLEET_TOKEN) and writes it to a blank board via lib/flash.ts. Gated on a
  // successful fleet compile because the artifact doesn't exist before then.
  // State machine: idle -> waiting (poll fleet status) -> flashing -> flashed
  // | error. See docs/lorawan/fleet-firmware-flash.md for the contract.
  type FlashState =
    | { kind: "idle" }
    | { kind: "waiting"; verdict: string }
    | { kind: "fetching" }
    | { kind: "flashing"; written: number; total: number }
    | { kind: "flashed"; bytes: number }
    | { kind: "error"; message: string };
  const [flashState, setFlashState] = useState<FlashState>({ kind: "idle" });
  const [serialLog, setSerialLog] = useState<string>("");
  const flashSessionRef = useRef<{ close: () => Promise<void> } | null>(null);

  // Release the WebSerial port when the dialog unmounts so a left-open monitor
  // doesn't hold the OS handle for the next provisioning attempt.
  useEffect(() => () => {
    void flashSessionRef.current?.close();
  }, []);

  async function handleFlash() {
    if (pushState.kind !== "pushed" || !pushState.run_id) return;
    const runId = pushState.run_id;
    setFlashState({ kind: "waiting", verdict: "running" });
    setSerialLog("");
    try {
      // 1. Wait for the compile to land. The fleet artifact endpoint 404s
      //    until the run finishes; polling the run-status endpoint is the
      //    canonical "is it ready" signal (reused from the push flow).
      while (true) {
        const status = await api.fleetRunStatus(runId);
        if (status.verdict === "passed") break;
        if (status.verdict === "failed" || status.verdict === "cancelled") {
          throw new Error(`compile ${status.verdict}`);
        }
        setFlashState({ kind: "waiting", verdict: status.verdict });
        await new Promise((r) => setTimeout(r, 2000));
      }
      // 2. Fetch the factory image -- blank-board flash at 0x0 + full erase.
      //    The provision step re-flushed DevNonces, so wiping NVS is safe
      //    (the §2.1 reasoning baked into flash.ts's docstring).
      setFlashState({ kind: "fetching" });
      const data = await api.fleetFirmware(runId, { factory: true });
      // 3. Dynamic-import the flasher so esptool-js stays out of the bundle
      //    until the user clicks (matches usb-detect's pattern).
      const { flashFirmware } = await import("../lib/flash");
      setFlashState({ kind: "flashing", written: 0, total: data.byteLength });
      const session = await flashFirmware({
        images: [{ data, address: 0x0 }],
        eraseAll: true,
        onProgress: (written, total) =>
          setFlashState({ kind: "flashing", written, total }),
        onSerial: (text) =>
          setSerialLog((s) => (s + text).slice(-8000)),
      });
      flashSessionRef.current = session;
      setFlashState({ kind: "flashed", bytes: data.byteLength });
    } catch (e) {
      let msg: string;
      if (e instanceof ApiError) {
        const detail = (e.body as { detail?: unknown } | undefined)?.detail;
        msg = `${e.status}: ${typeof detail === "string" ? detail : e.message}`;
      } else {
        msg = e instanceof Error ? e.message : String(e);
      }
      setFlashState({ kind: "error", message: msg });
    }
  }

  const devEuiValid = DEV_EUI_RE.test(devEui);
  // ChirpStack-not-available gates the Provision button. Status is null while
  // the initial probe is in flight; treat that as "not yet". When the probe
  // settles to available=true we let provisioning proceed.
  const chirpReady = chirpStatus?.available === true;
  const canProvision =
    eligible && devEuiValid && chirpReady && !provisioning && !result;

  return (
    <Dialog
      title="Provision LoRaWAN device"
      subtitle="Mint keys in ChirpStack for the lorawan-for-esphome external-component path."
      onClose={onClose}
      maxWidth="max-w-xl"
      footer={
        <>
          <Button onClick={onClose}>{result ? "Done" : "Cancel"}</Button>
          {!result && eligible && (
            <Button
              variant="primary"
              disabled={!canProvision}
              onClick={handleProvision}
              title={
                !chirpStatus
                  ? "Probing ChirpStack…"
                  : !chirpStatus.available
                    ? `ChirpStack unavailable: ${chirpStatus.reason ?? "unknown"}`
                    : !devEuiValid
                      ? "Enter a 16-hex-char DevEUI"
                      : undefined
              }
            >
              {provisioning ? "Provisioning…" : "Provision →"}
            </Button>
          )}
        </>
      }
    >
      <div className="space-y-4 text-sm">
          {/* Eligibility / context */}
          <div className="rounded-md border border-line bg-surface-2/40 p-3">
            <div className="text-[11px] uppercase tracking-wider text-ink-faint">design</div>
            <div className="mt-1 text-xs text-ink">
              <span className="text-ink-dim">{String((design as { name?: string }).name ?? "")}</span>{" "}
              <span className="text-ink-faint">({String((design as { id?: string }).id ?? "")})</span>
            </div>
            {!eligible ? (
              <div className="mt-2 text-xs text-amber-300">
                This design isn't eligible for the external-component path. Set{" "}
                <code className="rounded-md bg-surface-2 px-1">target: "esphome"</code> and add at
                least one entry to{" "}
                <code className="rounded-md bg-surface-2 px-1">lorawan.payload</code>, then reopen
                this dialog. The standalone Arduino path uses{" "}
                <em>Flash LoRaWAN firmware</em> instead.
              </div>
            ) : (
              <div className="mt-2 space-y-1 text-xs text-ink-dim">
                <div>
                  Payload fields:{" "}
                  <span className="text-ink">
                    {payloadFields.map((f) => f.sensor).join(", ")}
                  </span>
                </div>
                <div>
                  Band:{" "}
                  <span className="text-ink">
                    {lorawan?.region ?? "US915"} sub-band {lorawan?.sub_band ?? 2}
                  </span>
                </div>
              </div>
            )}
          </div>

          {/* DevEUI input */}
          {eligible && (
            <div className="space-y-1">
              <label className="block text-[11px] font-medium uppercase tracking-wider text-ink-faint">
                DevEUI (16 hex chars)
              </label>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={devEui}
                  onChange={(e) => {
                    setDevEui(e.target.value);
                    // A manual edit invalidates the previous detection hint.
                    setDetected(null);
                  }}
                  disabled={!!result}
                  placeholder="70b3d57ed0001234"
                  className="flex-1 rounded-md border border-line bg-surface-1 px-2.5 py-1.5 font-mono text-xs text-ink placeholder:text-ink-ghost transition-colors focus:border-accent-500/60 focus:outline-none disabled:opacity-60"
                />
                <Button
                  onClick={handleDetect}
                  disabled={!webSerial || detecting || !!result}
                  title={
                    webSerial
                      ? "Read the chip's eFuse MAC over WebSerial and derive the DevEUI (MAC-48 → EUI-64)"
                      : "WebSerial is unavailable in this browser; enter the DevEUI manually."
                  }
                >
                  {detecting ? "Detecting…" : "Detect from chip"}
                </Button>
              </div>
              <div className="text-[11px] text-ink-faint">
                {webSerial
                  ? "Derive from the chip's eFuse MAC over WebSerial, or type a manual override."
                  : "Manual entry only — WebSerial isn't available (try Chrome/Edge on desktop)."}
              </div>
              {detected && (
                <div className="text-[11px] text-emerald-300">
                  Derived from {detected.chipName} (MAC {detected.mac}).
                </div>
              )}
              {detectErr && (
                <div className="text-[11px] text-amber-400">detect failed: {detectErr}</div>
              )}
              {!devEuiValid && devEui.length > 0 && (
                <div className="text-[11px] text-amber-400">
                  Expected 16 hex characters; got {devEui.length}.
                </div>
              )}
            </div>
          )}

          {/* ChirpStack reachability/auth -- gates the Provision button. The
              endpoint is the same `chirpstack_status()` the CLI smoke uses;
              when it returns available=false, the reason is the gRPC status
              from the helper that wraps RpcError -> ChirpStackUnavailable. */}
          {eligible && chirpStatus && !chirpStatus.available && (
            <div className="rounded-md bg-amber-500/10 px-3 py-2 text-xs text-amber-200 ring-1 ring-amber-500/30">
              <div className="font-semibold">ChirpStack unavailable</div>
              <div className="mt-1 text-amber-200/80">
                {chirpStatus.reason ?? "unknown reason"}
                {chirpStatus.url && (
                  <>
                    {" "}
                    (server <code>{chirpStatus.url}</code>)
                  </>
                )}
              </div>
              <div className="mt-1 text-amber-300/70">
                Check <code>CHIRPSTACK_API_URL</code> / <code>CHIRPSTACK_API_TOKEN</code>
                {" "}on the server; the Bearer token comes from the ChirpStack UI under
                {" "}<strong>API Keys</strong>, not the JWT signing secret.
              </div>
            </div>
          )}

          {error && (
            <div className="rounded-md bg-rose-500/10 px-3 py-2 text-xs text-rose-200 ring-1 ring-rose-500/30">
              {error}
            </div>
          )}

          {/* Provisioned secrets */}
          {result && (
            <div className="space-y-2 rounded-md bg-emerald-500/10 p-3 ring-1 ring-emerald-500/30">
              <div className="flex items-center justify-between">
                <div className="text-[11px] uppercase tracking-wider text-emerald-300">
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
                className="w-full rounded-lg bg-surface-0 px-2 py-1.5 font-mono text-[12px] leading-relaxed text-emerald-100/90 ring-1 ring-line focus:outline-none"
              />
              <div className="flex items-center justify-between text-[11px]">
                <div className="text-emerald-200/80">
                  Drop these alongside the rendered ESPHome YAML as{" "}
                  <code className="rounded-md bg-emerald-500/15 px-1">secrets.yaml</code>. The
                  AppKey is shown once.
                </div>
                <button
                  onClick={handleCopy}
                  className="rounded-md bg-emerald-500/10 px-2 py-1 text-[11px] font-medium text-emerald-100 ring-1 ring-emerald-500/30 transition-colors hover:bg-emerald-500/20"
                >
                  {copied ? "Copied" : "Copy"}
                </button>
              </div>
            </div>
          )}

          {/* Push to fleet -- inline the secrets in the YAML so the operator
              doesn't need to edit fleet's secrets.yaml separately. */}
          {result && (
            <div className="rounded-md border border-line bg-surface-2/40 p-3">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-[11px] uppercase tracking-wider text-ink-faint">
                    push to fleet
                  </div>
                  <div className="mt-1 text-xs text-ink-dim">
                    Push the rendered YAML to fleet-for-esphome with these LoRaWAN keys
                    inlined, and enqueue an OTA compile.
                  </div>
                </div>
                <Button
                  variant="primary"
                  onClick={handlePushToFleet}
                  disabled={pushState.kind === "pushing" || pushState.kind === "pushed"}
                >
                  {pushState.kind === "pushing"
                    ? "Pushing…"
                    : pushState.kind === "pushed"
                      ? "Pushed"
                      : "Push to fleet →"}
                </Button>
              </div>
              {pushState.kind === "pushed" && (
                <div className="mt-2 text-xs text-emerald-300">
                  {pushState.created ? "Created" : "Updated"}{" "}
                  <code className="rounded-md bg-emerald-500/15 px-1">{pushState.filename}</code>{" "}
                  on the fleet.
                  {pushState.run_id && (
                    <> Compile enqueued (<code>{pushState.run_id}</code>).</>
                  )}
                </div>
              )}
              {pushState.kind === "error" && (
                <div className="mt-2 text-xs text-rose-400">
                  push failed: {pushState.message}
                </div>
              )}
            </div>
          )}

          {/* Flash via WebSerial -- pulls the fleet-built factory image
              through the studio (browser never holds FLEET_TOKEN) and
              writes it to a blank board. Appears only after a successful
              fleet push, since the artifact doesn't exist before then. */}
          {result && pushState.kind === "pushed" && pushState.run_id && (
            <div className="rounded-md border border-line bg-surface-2/40 p-3">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-[11px] uppercase tracking-wider text-ink-faint">
                    flash via WebSerial
                  </div>
                  <div className="mt-1 text-xs text-ink-dim">
                    Pull the fleet-built factory image and flash a blank board.
                    Waits for the compile to finish, then erase + write at 0x0.
                  </div>
                </div>
                <Button
                  variant="primary"
                  onClick={handleFlash}
                  disabled={
                    flashState.kind === "waiting" ||
                    flashState.kind === "fetching" ||
                    flashState.kind === "flashing" ||
                    flashState.kind === "flashed"
                  }
                  title={
                    flashState.kind === "flashed"
                      ? "Already flashed in this session"
                      : undefined
                  }
                >
                  {flashState.kind === "waiting"
                    ? `Waiting (${flashState.verdict})…`
                    : flashState.kind === "fetching"
                      ? "Fetching image…"
                      : flashState.kind === "flashing"
                        ? `Flashing ${Math.round((flashState.written / Math.max(flashState.total, 1)) * 100)}%`
                        : flashState.kind === "flashed"
                          ? "Flashed"
                          : "Flash via WebSerial →"}
                </Button>
              </div>
              {flashState.kind === "flashed" && (
                <div className="mt-2 text-xs text-emerald-300">
                  Wrote {flashState.bytes.toLocaleString()} bytes. Watch the
                  serial log below for the LoRaWAN join.
                </div>
              )}
              {flashState.kind === "error" && (
                <div className="mt-2 text-xs text-rose-400">
                  flash failed: {flashState.message}
                </div>
              )}
              {serialLog && (
                <pre className="mt-2 max-h-40 overflow-auto rounded-lg bg-surface-0 p-2 font-mono text-[12px] leading-relaxed text-ink-dim ring-1 ring-line">
                  {serialLog}
                </pre>
              )}
            </div>
          )}

          {/* Activation poll */}
          {result && (
            <div className="rounded-md border border-line bg-surface-2/40 p-3">
              <div className="text-[11px] uppercase tracking-wider text-ink-faint">
                join status
              </div>
              {activationErr ? (
                <div className="mt-1 text-xs text-rose-400">error: {activationErr}</div>
              ) : activation === null ? (
                <div className="mt-1 text-xs text-ink-faint">polling ChirpStack…</div>
              ) : activation.joined ? (
                <div className="mt-1 space-y-1 text-xs">
                  <div className="text-emerald-400">
                    joined · dev_addr <code>{activation.dev_addr}</code>
                  </div>
                  {typeof activation.f_cnt_up === "number" && (
                    <div className="text-ink-faint">uplink frames: {activation.f_cnt_up}</div>
                  )}
                </div>
              ) : (
                <div className="mt-1 text-xs text-amber-300">
                  waiting for OTAA join… (build + flash the firmware, then check back)
                </div>
              )}
            </div>
          )}

      </div>
    </Dialog>
  );
}
