import { afterEach, describe, expect, it, vi } from "vitest";
import { api, lorawanCompile } from "./client";
import type { Design, LorawanCompileEvent } from "../types/api";

function jsonResponse(data: unknown, ok = true): Response {
  return { ok, json: async () => data, text: async () => JSON.stringify(data) } as unknown as Response;
}

function sseResponse(text: string, ok = true): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(text));
      controller.close();
    },
  });
  return { ok, body, json: async () => ({}) } as unknown as Response;
}

const DESIGN: Design = { schema_version: "0.1", id: "d", name: "D", target: "lorawan" };

describe("lorawanCompile SSE parsing", () => {
  afterEach(() => vi.restoreAllMocks());

  it("yields log chunks then the done frame", async () => {
    const sse =
      'data: {"type":"log","data":"compiling"}\n\n' +
      'data: {"type":"done","ok":true,"cache_key":"abc123","cache_hit":true,"env":"ttgo-lora32-v1","bin":"/x"}\n\n';
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(sseResponse(sse)));

    const events: LorawanCompileEvent[] = [];
    for await (const e of lorawanCompile(DESIGN)) events.push(e);

    expect(events[0]).toEqual({ type: "log", data: "compiling" });
    const done = events.at(-1);
    expect(done).toMatchObject({ type: "done", ok: true, cache_key: "abc123", cache_hit: true });
  });

  it("throws on an event: error frame", async () => {
    const sse = 'event: error\ndata: {"message":"PlatformIO not found"}\n\n';
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(sseResponse(sse)));
    await expect(lorawanCompile(DESIGN).next()).rejects.toThrow(/PlatformIO not found/);
  });

  it("throws ApiError on a non-2xx response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(sseResponse("", false)));
    await expect(lorawanCompile(DESIGN).next()).rejects.toThrow(/lorawan\/compile/);
  });
});

describe("inventory client", () => {
  afterEach(() => vi.restoreAllMocks());

  it("listInventory GETs /inventory", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse([{ library_id: "bme280", kind: "component", quantity: 2, location: "", note: "" }]),
    );
    vi.stubGlobal("fetch", fetchMock);
    const r = await api.listInventory();
    expect(fetchMock.mock.calls[0][0]).toContain("/inventory");
    expect(r[0].library_id).toBe("bme280");
  });

  it("setInventory PUTs the body to the part's path", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ library_id: "ssd1306", kind: "component", quantity: 3, location: "A1", note: "" }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await api.setInventory("ssd1306", { kind: "component", quantity: 3, location: "A1" });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain("/inventory/ssd1306");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body)).toMatchObject({ quantity: 3, location: "A1" });
  });

  it("deleteInventory DELETEs", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ deleted: "bme280" }));
    vi.stubGlobal("fetch", fetchMock);
    const r = await api.deleteInventory("bme280");
    expect(fetchMock.mock.calls[0][1].method).toBe("DELETE");
    expect(r.deleted).toBe("bme280");
  });

  it("checkDesignInventory POSTs the design", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ design_id: "d", lines: [], summary: { have: 0, partial: 0, need: 0 } }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const r = await api.checkDesignInventory(DESIGN);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain("/design/inventory/check");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body).design.id).toBe("d");
    expect(r.summary.need).toBe(0);
  });
});
