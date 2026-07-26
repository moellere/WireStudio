import { describe, expect, it } from "vitest";

import { tasmotaConfigCommands, type TasmotaTemplate } from "./tasmota";

const template: TasmotaTemplate = {
  NAME: "smart-plug",
  GPIO: [160, 3072, 0, 3104, 0, 0, 0, 0, 224, 0, 0, 0, 0, 0],
  FLAG: 0,
  BASE: 18,
};

describe("tasmotaConfigCommands", () => {
  it("emits template + module activation as one backlog", () => {
    const cmds = tasmotaConfigCommands(template);
    expect(cmds).toHaveLength(1);
    expect(cmds[0]).toBe(
      `Backlog0 Template ${JSON.stringify(template)}; Module 0`,
    );
  });

  it("appends wifi credentials as a second backlog", () => {
    const cmds = tasmotaConfigCommands(template, "dorkiot", "hunter2");
    expect(cmds).toHaveLength(2);
    expect(cmds[1]).toBe("Backlog0 SSId1 dorkiot; Password1 hunter2");
  });

  it("ssid without password omits Password1", () => {
    const cmds = tasmotaConfigCommands(template, "dorkiot");
    expect(cmds[1]).toBe("Backlog0 SSId1 dorkiot");
  });

  it("password without ssid pushes no wifi commands", () => {
    expect(tasmotaConfigCommands(template, undefined, "hunter2")).toHaveLength(1);
  });
});
