import { useState } from "react";
import { ApiError, api } from "../api/client";
import type { LibraryCheckResponse } from "../types/api";
import { Button, Dialog } from "./ui";

export const NEW_COMPONENT_TEMPLATE = `id: my_component
name: My component
category: sensor
use_cases: []
electrical:
  vcc_min: 3.0
  vcc_max: 3.6
  pins:
  - {role: VCC, kind: power}
  - {role: GND, kind: ground}
  - {role: OUT, kind: digital_in, voltage: 3.3}
esphome:
  required_components: []
  yaml_template: |
    binary_sensor:
      - platform: gpio
        pin: {{ pins.OUT | tojson }}
        name: "{{ label }}"
        id: {{ id }}
kicad:
  symbol_lib: Connector_Generic
  symbol: Conn_01x03
  footprint: Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical
`;

export const NEW_BOARD_TEMPLATE = `id: my_board
name: My board
mcu: esp32
chip_variant: esp32
framework: arduino
platformio_board: esp32dev
flash_size_mb: 4
rails:
  - {name: "5V", voltage: 5.0, source: usb}
  - {name: "3V3", voltage: 3.3, source: onboard_regulator}
  - {name: "GND", voltage: 0.0}
default_buses:
  i2c: {sda: GPIO21, scl: GPIO22}
onboard_peripherals:
  led: {pin: GPIO2}
gpio_capabilities:
  GPIO2:  [gpio, pwm, builtin_led]
  GPIO4:  [gpio, adc, adc2, pwm]
  GPIO21: [gpio, pwm, i2c_sda]
  GPIO22: [gpio, pwm, i2c_scl]
  GPIO34: [gpio, adc, adc1, input_only]
`;

export type LibraryKind = "component" | "board";

const GATES: Record<LibraryKind, {
  check: (yaml: string) => Promise<LibraryCheckResponse>;
  create: (yaml: string, overwrite: boolean) => Promise<LibraryCheckResponse>;
  subtitle: string;
}> = {
  component: {
    check: (yaml) => api.checkComponentYaml(yaml),
    create: (yaml, overwrite) => api.createComponent(yaml, overwrite),
    subtitle: "Checked like a bundled component: schema, subcircuit nets, template render, KiCad symbols when the libraries are installed. Nothing is simulated.",
  },
  board: {
    check: (yaml) => api.checkBoardYaml(yaml),
    create: (yaml, overwrite) => api.createBoard(yaml, overwrite),
    subtitle: "Checked like a bundled board: schema, every bus and onboard pin against the GPIO list, KiCad symbol pins, enclosure geometry, and an ESPHome render with the onboard parts. The pinout is not checked against the datasheet.",
  },
};

function reportFromError(e: unknown): LibraryCheckResponse | null {
  if (e instanceof ApiError && e.body && typeof e.body === "object" && "errors" in (e.body as object)) {
    return e.body as LibraryCheckResponse;
  }
  return null;
}

/** Author or edit a library component or board as YAML: check it against
 * the same gate every bundled entry passes, then save into the user library. */
export function LibraryEditorDialog({
  kind = "component",
  title,
  initialYaml,
  overwrite,
  onClose,
  onSaved,
}: {
  kind?: LibraryKind;
  title: string;
  initialYaml: string;
  overwrite: boolean;
  onClose: () => void;
  onSaved: (libraryId: string) => void;
}) {
  const [yaml, setYaml] = useState(initialYaml);
  const [report, setReport] = useState<LibraryCheckResponse | null>(null);
  const [busy, setBusy] = useState<"check" | "save" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const gate = GATES[kind];

  async function check() {
    setBusy("check");
    setError(null);
    try {
      setReport(await gate.check(yaml));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  async function save() {
    setBusy("save");
    setError(null);
    try {
      const r = await gate.create(yaml, overwrite);
      setReport(r);
      if (r.ok) onSaved(r.library_id);
    } catch (e) {
      const r = reportFromError(e);
      if (r) setReport(r);
      else setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <Dialog
      title={title}
      subtitle={gate.subtitle}
      onClose={onClose}
      maxWidth="max-w-3xl"
      footer={
        <div className="flex items-center justify-end gap-2">
          <Button onClick={onClose}>Close</Button>
          <Button onClick={check} disabled={busy !== null}>
            {busy === "check" ? "Checking…" : "Check"}
          </Button>
          <Button variant="primary" onClick={save} disabled={busy !== null}>
            {busy === "save" ? "Saving…" : overwrite ? "Save" : "Create"}
          </Button>
        </div>
      }
    >
      <textarea
        value={yaml}
        onChange={(e) => setYaml(e.target.value)}
        spellCheck={false}
        className="h-80 w-full resize-y rounded-md border border-line bg-surface-2/40 p-2 font-mono text-xs text-ink"
      />
      {error && <p className="mt-2 text-xs text-rose-300">{error}</p>}
      {report && (
        <div className="mt-2 space-y-1.5 text-xs" data-testid="library-check-report">
          <p className={report.ok ? "text-emerald-300" : "text-rose-300"}>
            {report.ok ? `${report.library_id}: passes` : `${report.library_id || kind}: ${report.errors.length} error(s)`}
            {report.saved ? ` — saved to ${report.saved}` : ""}
          </p>
          {report.errors.map((line) => <p key={line} className="text-rose-300">✕ {line}</p>)}
          {report.verified.map((line) => <p key={line} className="text-emerald-300">✓ {line}</p>)}
          {report.warnings.map((line) => <p key={line} className="text-amber-300">! {line}</p>)}
          {report.unverified.map((line) => <p key={line} className="text-ink-dim">? {line}</p>)}
          {report.not_checked.map((line) => <p key={line} className="text-ink-faint">– {line}</p>)}
        </div>
      )}
    </Dialog>
  );
}
