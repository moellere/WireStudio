import { describe, expect, it } from "vitest";
import {
  addRequirement,
  addWarning,
  isDirty,
  readBuses,
  readComponents,
  readConnections,
  readRequirements,
  readWarnings,
  removeRequirement,
  removeWarning,
  setBoardLibraryId,
  setFleetField,
  updateComponentParam,
  updateConnectionTarget,
  updateRequirement,
  updateWarning,
} from "./design";
import type { Design } from "../types/api";

const baseDesign: Design = {
  schema_version: "0.1",
  id: "test",
  name: "test",
  board: { library_id: "wemos-d1-mini", mcu: "esp8266" },
  components: [
    { id: "pir1", library_id: "hc-sr501", label: "PIR", params: { filters: [{ delayed_on: "100ms" }] } },
    { id: "bme1", library_id: "bme280", label: "BME", params: { address: "0x76" } },
  ],
  buses: [
    { id: "i2c0", type: "i2c", sda: "D2", scl: "D1" },
  ],
  connections: [
    { component_id: "pir1", pin_role: "OUT", target: { kind: "gpio", pin: "D2" } },
    { component_id: "bme1", pin_role: "SDA", target: { kind: "bus", bus_id: "i2c0" } },
  ],
  requirements: [{ id: "r1", kind: "capability", text: "detect motion" }],
  warnings: [],
  fleet: { device_name: "test", tags: ["indoor"] },
};

function clone<T>(v: T): T {
  return JSON.parse(JSON.stringify(v)) as T;
}

describe("readers", () => {
  it("readComponents lifts ids/library_ids/params", () => {
    const cs = readComponents(baseDesign);
    expect(cs.map((c) => c.id)).toEqual(["pir1", "bme1"]);
    expect(cs[1].params).toEqual({ address: "0x76" });
  });

  it("readBuses returns id+type", () => {
    expect(readBuses(baseDesign)).toEqual([{ id: "i2c0", type: "i2c" }]);
  });

  it("readConnections optionally filters by component", () => {
    expect(readConnections(baseDesign).length).toBe(2);
    expect(readConnections(baseDesign, "bme1").length).toBe(1);
    expect(readConnections(baseDesign, "bme1")[0].pin_role).toBe("SDA");
  });

  it("readRequirements / readWarnings normalize shape", () => {
    expect(readRequirements(baseDesign)[0]).toEqual({ id: "r1", kind: "capability", text: "detect motion" });
    expect(readWarnings(baseDesign)).toEqual([]);
  });
});

describe("updateComponentParam", () => {
  it("patches the matching component immutably", () => {
    const before = clone(baseDesign);
    const next = updateComponentParam(baseDesign, "bme1", "address", "0x77");
    expect(((next.components as Array<{ id: string; params?: Record<string, unknown> }>).find((c) => c.id === "bme1"))?.params)
      .toEqual({ address: "0x77" });
    // Original untouched.
    expect(baseDesign).toEqual(before);
  });

  it("undefined deletes the key", () => {
    const next = updateComponentParam(baseDesign, "pir1", "filters", undefined);
    const pir1 = (next.components as Array<{ id: string; params?: Record<string, unknown> }>).find((c) => c.id === "pir1");
    expect(pir1?.params).toEqual({});
  });

  it("ignores unknown component ids", () => {
    const next = updateComponentParam(baseDesign, "ghost", "x", 1);
    expect(next.components).toEqual(baseDesign.components);
  });
});

describe("updateConnectionTarget", () => {
  it("replaces the indexed connection's target", () => {
    const next = updateConnectionTarget(baseDesign, 0, { kind: "gpio", pin: "D5" });
    const c = (next.connections as Array<{ target: { kind: string; pin?: string } }>)[0];
    expect(c.target).toEqual({ kind: "gpio", pin: "D5" });
  });

  it("supports kind switching", () => {
    const next = updateConnectionTarget(baseDesign, 0, {
      kind: "expander_pin", expander_id: "hub", number: 3, mode: "INPUT_PULLUP", inverted: true,
    });
    const c = (next.connections as Array<{ target: { kind: string } }>)[0];
    expect(c.target).toEqual({
      kind: "expander_pin", expander_id: "hub", number: 3, mode: "INPUT_PULLUP", inverted: true,
    });
  });

  it("does not mutate the input", () => {
    const before = clone(baseDesign);
    updateConnectionTarget(baseDesign, 1, { kind: "gpio", pin: "D9" });
    expect(baseDesign).toEqual(before);
  });
});

describe("requirements + warnings", () => {
  it("addRequirement auto-ids skipping collisions", () => {
    const next = addRequirement(baseDesign);
    const reqs = next.requirements as Array<{ id: string }>;
    expect(reqs.length).toBe(2);
    expect(reqs[1].id).toBe("r2");
  });

  it("updateRequirement patches text/kind", () => {
    const next = updateRequirement(baseDesign, 0, { text: "new", kind: "constraint" });
    expect((next.requirements as Array<{ id: string; text: string; kind: string }>)[0])
      .toMatchObject({ id: "r1", text: "new", kind: "constraint" });
  });

  it("removeRequirement removes the indexed entry", () => {
    const next = removeRequirement(baseDesign, 0);
    expect(next.requirements).toEqual([]);
  });

  it("warnings can be added, edited, removed", () => {
    let d = addWarning(baseDesign);
    expect((d.warnings as unknown[]).length).toBe(1);
    d = updateWarning(d, 0, { code: "x", text: "boom", level: "error" });
    expect((d.warnings as Array<{ code: string }>)[0].code).toBe("x");
    d = removeWarning(d, 0);
    expect(d.warnings).toEqual([]);
  });
});

describe("board + fleet", () => {
  it("setBoardLibraryId replaces library_id and mcu while preserving extras", () => {
    const designWithExtra: Design = clone(baseDesign);
    (designWithExtra.board as Record<string, unknown>).framework = "arduino";
    const next = setBoardLibraryId(designWithExtra, "esp32-devkitc-v4", "esp32");
    expect(next.board).toEqual({
      library_id: "esp32-devkitc-v4",
      mcu: "esp32",
      framework: "arduino",
    });
  });

  it("setFleetField patches a single key", () => {
    const next = setFleetField(baseDesign, "device_name", "renamed");
    expect((next.fleet as Record<string, unknown>).device_name).toBe("renamed");
    expect((next.fleet as Record<string, unknown>).tags).toEqual(["indoor"]);
  });

  it("setFleetField creates fleet if missing", () => {
    const designNoFleet: Design = { ...baseDesign };
    delete (designNoFleet as Record<string, unknown>).fleet;
    const next = setFleetField(designNoFleet, "device_name", "fresh");
    expect(next.fleet).toEqual({ device_name: "fresh" });
  });
});

describe("isDirty", () => {
  it("returns false for null inputs", () => {
    expect(isDirty(null, baseDesign)).toBe(false);
    expect(isDirty(baseDesign, null)).toBe(false);
  });

  it("returns false for the same reference", () => {
    expect(isDirty(baseDesign, baseDesign)).toBe(false);
  });

  it("returns true after a mutating helper runs", () => {
    const next = updateComponentParam(baseDesign, "bme1", "address", "0x77");
    expect(isDirty(baseDesign, next)).toBe(true);
  });
});
