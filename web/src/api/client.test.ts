import { afterEach, describe, expect, it, vi } from "vitest";
import { lorawanCompile } from "./client";
import type { Design, LorawanCompileEvent } from "../types/api";

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
