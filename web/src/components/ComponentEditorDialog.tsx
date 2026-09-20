import { useState } from "react";
import { ApiError, api } from "../api/client";
import type { ComponentCheckResponse } from "../types/api";
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

function reportFromError(e: unknown): ComponentCheckResponse | null {
  if (e instanceof ApiError && e.body && typeof e.body === "object" && "errors" in (e.body as object)) {
    return e.body as ComponentCheckResponse;
  }
  return null;
}

/** Author or edit a library component as YAML: check it against the same
 * gate every bundled component passes, then save into the user library. */
export function ComponentEditorDialog({
  title,
  initialYaml,
  overwrite,
  onClose,
  onSaved,
}: {
  title: string;
  initialYaml: string;
  overwrite: boolean;
  onClose: () => void;
  onSaved: (libraryId: string) => void;
}) {
  const [yaml, setYaml] = useState(initialYaml);
  const [report, setReport] = useState<ComponentCheckResponse | null>(null);
  const [busy, setBusy] = useState<"check" | "save" | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function check() {
    setBusy("check");
    setError(null);
    try {
      setReport(await api.checkComponentYaml(yaml));
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
      const r = await api.createComponent(yaml, overwrite);
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
      subtitle="Checked like a bundled component: schema, subcircuit nets, template render, KiCad symbols when the libraries are installed. Nothing is simulated."
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
        <div className="mt-2 space-y-1.5 text-xs" data-testid="component-check-report">
          <p className={report.ok ? "text-emerald-300" : "text-rose-300"}>
            {report.ok ? `${report.library_id}: passes` : `${report.library_id || "component"}: ${report.errors.length} error(s)`}
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
