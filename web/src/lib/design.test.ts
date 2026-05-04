import { describe, expect, it } from "vitest";
import {
  addBus,
  addComponent,
  addRequirement,
  addWarning,
  isDirty,
  neededBusTypes,
  nextInstanceId,
  prepareBusesForLib,
  readBuses,
  readComponents,
  readConnections,
  readRequirements,
  readWarnings,
  removeBus,
  removeComponent,
  removeRequirement,
  removeWarning,
  setBoardLibraryId,
  setFleetField,
  setLockedPin,
  updateBus,
  updateComponentParam,
  updateConnectionTarget,
  updateRequirement,
  updateWarning,
  type LibraryComponentDetail,
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

describe("nextInstanceId", () => {
  it("falls back to library id + counter", () => {
    expect(nextInstanceId(baseDesign, "ssd1306")).toBe("ssd1306_1");
  });

  it("skips ids already used", () => {
    const d: Design = clone(baseDesign);
    (d.components as Array<{ id: string }>).push({ id: "ssd1306_1" } as never);
    expect(nextInstanceId(d, "ssd1306")).toBe("ssd1306_2");
  });

  it("respects a hint when free", () => {
    expect(nextInstanceId(baseDesign, "ssd1306", "front_oled")).toBe("front_oled");
  });
});

describe("addComponent", () => {
  const bme: LibraryComponentDetail = {
    id: "bme280",
    name: "Bosch BME280 (T/H/P)",
    category: "sensor",
    electrical: {
      vcc_min: 1.8,
      vcc_max: 3.6,
      pins: [
        { role: "VCC", kind: "power" },
        { role: "GND", kind: "ground" },
        { role: "SDA", kind: "i2c_sda" },
        { role: "SCL", kind: "i2c_scl" },
      ],
    },
  };

  const board = {
    rails: [
      { name: "5V", voltage: 5.0 },
      { name: "3V3", voltage: 3.3 },
      { name: "GND", voltage: 0.0 },
    ],
  };

  it("appends a new component with auto-id", () => {
    const next = addComponent(baseDesign, bme, { board, buses: readBuses(baseDesign) });
    const cs = next.components as Array<{ id: string; library_id: string }>;
    expect(cs.length).toBe(3);
    expect(cs[2].id).toBe("bme280_1");
    expect(cs[2].library_id).toBe("bme280");
  });

  it("auto-creates one connection per library pin", () => {
    const next = addComponent(baseDesign, bme, { board, buses: readBuses(baseDesign) });
    const newConns = (next.connections as Array<{ component_id: string }>).filter((c) => c.component_id === "bme280_1");
    expect(newConns.length).toBe(4);
  });

  it("VCC picks the lowest rail satisfying the part's range", () => {
    const next = addComponent(baseDesign, bme, { board, buses: [] });
    const conns = (next.connections as Array<{ component_id: string; pin_role: string; target: { kind: string; rail?: string } }>);
    const vcc = conns.find((c) => c.component_id === "bme280_1" && c.pin_role === "VCC");
    expect(vcc?.target).toEqual({ kind: "rail", rail: "3V3" });
  });

  it("GND picks the rail at 0V", () => {
    const next = addComponent(baseDesign, bme, { board, buses: [] });
    const conns = (next.connections as Array<{ component_id: string; pin_role: string; target: { kind: string; rail?: string } }>);
    const gnd = conns.find((c) => c.component_id === "bme280_1" && c.pin_role === "GND");
    expect(gnd?.target).toEqual({ kind: "rail", rail: "GND" });
  });

  it("i2c pins link to a matching bus when present", () => {
    const next = addComponent(baseDesign, bme, { board, buses: readBuses(baseDesign) });
    const conns = (next.connections as Array<{ component_id: string; pin_role: string; target: { kind: string; bus_id?: string } }>);
    const sda = conns.find((c) => c.component_id === "bme280_1" && c.pin_role === "SDA");
    expect(sda?.target).toEqual({ kind: "bus", bus_id: "i2c0" });
  });

  it("i2c pins emit empty-bus targets when no matching bus exists", () => {
    const designNoBus: Design = clone(baseDesign);
    designNoBus.buses = [];
    const next = addComponent(designNoBus, bme, { board, buses: [] });
    const conns = (next.connections as Array<{ component_id: string; pin_role: string; target: { kind: string; bus_id?: string } }>);
    const sda = conns.find((c) => c.component_id === "bme280_1" && c.pin_role === "SDA");
    expect(sda?.target).toEqual({ kind: "bus", bus_id: "" });
  });

  it("digital_in / digital_out get gpio placeholders", () => {
    const button: LibraryComponentDetail = {
      id: "gpio_input",
      name: "Generic GPIO binary sensor",
      electrical: { pins: [{ role: "IN", kind: "digital_in" }] },
    };
    const next = addComponent(baseDesign, button, { board, buses: [] });
    const conns = (next.connections as Array<{ component_id: string; pin_role: string; target: { kind: string; pin?: string } }>);
    const inConn = conns.find((c) => c.pin_role === "IN" && c.component_id === "gpio_input_1");
    expect(inConn?.target).toEqual({ kind: "gpio", pin: "" });
  });

  it("does not mutate the input", () => {
    const before = clone(baseDesign);
    addComponent(baseDesign, bme, { board, buses: readBuses(baseDesign) });
    expect(baseDesign).toEqual(before);
  });
});

describe("neededBusTypes + prepareBusesForLib", () => {
  const bme: LibraryComponentDetail = {
    id: "bme280", name: "BME280",
    electrical: {
      pins: [
        { role: "VCC", kind: "power" }, { role: "GND", kind: "ground" },
        { role: "SDA", kind: "i2c_sda" }, { role: "SCL", kind: "i2c_scl" },
      ],
    },
  };
  const sx127x: LibraryComponentDetail = {
    id: "sx127x", name: "SX127x",
    electrical: {
      pins: [
        { role: "VCC", kind: "power" }, { role: "GND", kind: "ground" },
        { role: "SCK", kind: "spi_clk" }, { role: "MOSI", kind: "spi_mosi" }, { role: "MISO", kind: "spi_miso" },
        { role: "CS", kind: "spi_cs" },
      ],
    },
  };
  const board = {
    rails: [{ name: "3V3", voltage: 3.3 }, { name: "GND", voltage: 0 }],
    default_buses: { i2c: { sda: "D2", scl: "D1" }, spi: { clk: "GPIO5", miso: "GPIO19", mosi: "GPIO27" } },
  };

  it("neededBusTypes pulls types from pin kinds", () => {
    expect([...neededBusTypes(bme)]).toEqual(["i2c"]);
    expect([...neededBusTypes(sx127x)]).toEqual(["spi"]);
  });

  it("does nothing when the design already has the needed bus", () => {
    const next = prepareBusesForLib(baseDesign, bme, board);
    expect(next.buses).toEqual(baseDesign.buses); // i2c0 already present
  });

  it("appends a bus seeded from the board's default_buses", () => {
    const designNoSpi: Design = clone(baseDesign);
    const next = prepareBusesForLib(designNoSpi, sx127x, board);
    const buses = next.buses as Array<{ id: string; type: string; clk?: string; miso?: string; mosi?: string }>;
    expect(buses.length).toBe(2);
    const spi = buses.find((b) => b.type === "spi");
    expect(spi).toMatchObject({ id: "spi0", type: "spi", clk: "GPIO5", miso: "GPIO19", mosi: "GPIO27" });
  });

  it("falls back to a bare bus skeleton when the board has no default", () => {
    const designNoSpi: Design = clone(baseDesign);
    const next = prepareBusesForLib(designNoSpi, sx127x, { rails: board.rails });
    const buses = next.buses as Array<{ id: string; type: string }>;
    const spi = buses.find((b) => b.type === "spi");
    expect(spi).toEqual({ id: "spi0", type: "spi" });
  });

  it("auto-id avoids existing bus ids", () => {
    const d: Design = clone(baseDesign);
    (d.buses as Array<Record<string, unknown>>).push({ id: "spi0", type: "spi", clk: "X" });
    const next = prepareBusesForLib(d, sx127x, board);
    // spi already present (id spi0) -> nothing appended.
    expect((next.buses as unknown[]).length).toBe(2);
  });

  it("addComponent on a design lacking buses now yields renderable connections", () => {
    const designNoI2c: Design = { ...clone(baseDesign), buses: [] };
    const withBuses = prepareBusesForLib(designNoI2c, bme, board);
    const next = addComponent(withBuses, bme, {
      board, buses: readBuses(withBuses),
    });
    const conns = next.connections as Array<{ component_id: string; pin_role: string; target: { kind: string; bus_id?: string } }>;
    const sda = conns.find((c) => c.component_id === "bme280_1" && c.pin_role === "SDA");
    expect(sda?.target).toEqual({ kind: "bus", bus_id: "i2c0" });
  });
});

describe("removeComponent", () => {
  it("drops the named instance from components", () => {
    const next = removeComponent(baseDesign, "bme1");
    const ids = (next.components as Array<{ id: string }>).map((c) => c.id);
    expect(ids).toEqual(["pir1"]);
  });

  it("drops connections originating from the instance", () => {
    const next = removeComponent(baseDesign, "bme1");
    const conns = next.connections as Array<{ component_id: string }>;
    expect(conns.every((c) => c.component_id !== "bme1")).toBe(true);
    expect(conns.length).toBe(1); // only pir1.OUT remains
  });

  it("leaves connections that target the removed id (orphans surface in UI)", () => {
    const designWithExpander: Design = clone(baseDesign);
    (designWithExpander.connections as Array<Record<string, unknown>>).push({
      component_id: "pir1",
      pin_role: "OUT",
      target: { kind: "expander_pin", expander_id: "bme1", number: 0 },
    });
    const next = removeComponent(designWithExpander, "bme1");
    const conns = next.connections as Array<{ target: { kind: string; expander_id?: string } }>;
    expect(conns.some((c) => c.target.expander_id === "bme1")).toBe(true);
  });

  it("is a no-op for unknown ids", () => {
    const next = removeComponent(baseDesign, "ghost");
    expect(next.components).toEqual(baseDesign.components);
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


describe("locked_pins", () => {
  it("readConnections lifts locked_pin from the matching component", () => {
    const d = clone(baseDesign);
    (d.components as Array<Record<string, unknown>>)[0].locked_pins = { OUT: "D5" };
    const rows = readConnections(d, "pir1");
    expect(rows[0].locked_pin).toBe("D5");
  });

  it("readConnections leaves locked_pin null when no lock exists", () => {
    const rows = readConnections(baseDesign, "pir1");
    expect(rows[0].locked_pin).toBeNull();
  });

  it("setLockedPin writes a new entry", () => {
    const next = setLockedPin(baseDesign, "pir1", "OUT", "D6");
    const c = (next.components as Array<Record<string, unknown>>)[0];
    expect(c.locked_pins).toEqual({ OUT: "D6" });
    // input unchanged
    expect((baseDesign.components as Array<Record<string, unknown>>)[0].locked_pins).toBeUndefined();
  });

  it("setLockedPin removes the field entirely when the map empties", () => {
    const seeded = setLockedPin(baseDesign, "pir1", "OUT", "D6");
    const cleared = setLockedPin(seeded, "pir1", "OUT", null);
    const c = (cleared.components as Array<Record<string, unknown>>)[0];
    expect(c.locked_pins).toBeUndefined();
  });

  it("setLockedPin treats empty string the same as null", () => {
    const seeded = setLockedPin(baseDesign, "pir1", "OUT", "D6");
    const cleared = setLockedPin(seeded, "pir1", "OUT", "");
    const c = (cleared.components as Array<Record<string, unknown>>)[0];
    expect(c.locked_pins).toBeUndefined();
  });

  it("setLockedPin preserves locks for sibling roles", () => {
    const seeded = setLockedPin(baseDesign, "pir1", "OUT", "D6");
    const next = setLockedPin(seeded, "pir1", "VCC", "5V");
    const c = (next.components as Array<Record<string, unknown>>)[0];
    expect(c.locked_pins).toEqual({ OUT: "D6", VCC: "5V" });
  });

  it("setLockedPin is a no-op for unknown component ids", () => {
    const next = setLockedPin(baseDesign, "ghost", "OUT", "D6");
    expect(next.components).toEqual(baseDesign.components);
  });
});

describe("buses", () => {
  it("addBus appends a fresh bus with auto-id", () => {
    const next = addBus(baseDesign, "spi");
    const buses = next.buses as Array<Record<string, unknown>>;
    expect(buses.length).toBe(2);
    expect(buses[1]).toMatchObject({ id: "spi0", type: "spi" });
  });

  it("addBus skips ids already used", () => {
    const seeded = addBus(baseDesign, "i2c");
    const buses = seeded.buses as Array<Record<string, unknown>>;
    // baseDesign has i2c0; addBus must pick i2c1.
    expect(buses[1]).toMatchObject({ id: "i2c1", type: "i2c" });
  });

  it("addBus seeds from defaults when provided", () => {
    const next = addBus(baseDesign, "uart", { tx: "D1", rx: "D2", baud_rate: "9600" });
    const buses = next.buses as Array<Record<string, unknown>>;
    expect(buses[1]).toMatchObject({ id: "uart0", type: "uart", tx: "D1", rx: "D2" });
  });

  it("updateBus patches a single bus immutably", () => {
    const next = updateBus(baseDesign, "i2c0", { sda: "D6", frequency_hz: 400000 });
    const b = (next.buses as Array<Record<string, unknown>>)[0];
    expect(b).toMatchObject({ id: "i2c0", sda: "D6", scl: "D1", frequency_hz: 400000 });
    // input untouched
    expect((baseDesign.buses as Array<Record<string, unknown>>)[0]).not.toMatchObject({ sda: "D6" });
  });

  it("removeBus drops the matching bus and leaves others alone", () => {
    const seeded = addBus(baseDesign, "spi");
    const next = removeBus(seeded, "i2c0");
    const buses = next.buses as Array<Record<string, unknown>>;
    expect(buses.map((b) => b.id)).toEqual(["spi0"]);
  });

  it("removeBus on unknown id is a no-op", () => {
    const next = removeBus(baseDesign, "ghost");
    expect(next.buses).toEqual(baseDesign.buses);
  });
});
