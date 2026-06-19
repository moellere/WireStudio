import type {
  AgentSession,
  AgentStatus,
  AgentStreamEvent,
  AgentTurnResponse,
  BoardSummary,
  ComponentSummary,
  EnclosureSearchResponse,
  EnclosureSearchStatus,
  ExampleSummary,
  FleetJobLogResponse,
  FleetPushResponse,
  FleetRunStatus,
  FleetStatus,
  InventoryEntry,
  InventoryCheckResponse,
  FabStatus,
  KicadPcbStatus,
  KicadRenderStatus,
  LorawanCompileEvent,
  LorawanCompileStatus,
  LorawanProvisionResponse,
  LorawanProvisionEsphomeResponse,
  LorawanActivationResponse,
  ModuleSummary,
  RecommendConstraints,
  RecommendResponse,
  UseCaseEntry,
  RenderResponse,
  SaveDesignResponse,
  SavedDesignSummary,
  SolvePinsResponse,
  ValidateResponse,
  Design,
} from "../types/api";

// In dev, Vite proxies /api/* to the studio API on :8765 (see vite.config.ts).
// In production, set VITE_API_BASE to the API origin or keep it empty if the
// API is served from the same origin under /api/.
const API_BASE = import.meta.env.VITE_API_BASE ?? "/api";

class ApiError extends Error {
  status: number;
  body: unknown;
  constructor(status: number, message: string, body?: unknown) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!res.ok) {
    let body: unknown = undefined;
    try { body = await res.json(); } catch { /* not json */ }
    throw new ApiError(res.status, `${init?.method ?? "GET"} ${path} -> ${res.status}`, body);
  }
  return (await res.json()) as T;
}

/** Like `request` but expects a text/plain response (used for the OpenSCAD
 *  enclosure download). Errors still come back as JSON, so the failure
 *  parsing is shared. */
async function requestText(path: string, init?: RequestInit): Promise<string> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!res.ok) {
    let body: unknown = undefined;
    try { body = await res.json(); } catch { /* not json */ }
    throw new ApiError(res.status, `${init?.method ?? "GET"} ${path} -> ${res.status}`, body);
  }
  return await res.text();
}

/** Like `request` but expects a binary response (used for the fab-package
 *  zip). Errors still come back as JSON. */
async function requestBlob(path: string, init?: RequestInit): Promise<Blob> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!res.ok) {
    let body: unknown = undefined;
    try { body = await res.json(); } catch { /* not json */ }
    throw new ApiError(res.status, `${init?.method ?? "GET"} ${path} -> ${res.status}`, body);
  }
  return await res.blob();
}

export const api = {
  health: () => request<{ ok: boolean; version: string }>("/health"),

  listBoards: () => request<BoardSummary[]>("/library/boards"),
  /** Boards selectable by a generation target (e.g. "lorawan" -> radio boards). */
  listBoardsForTarget: (target: string) =>
    request<BoardSummary[]>(`/library/boards?target=${encodeURIComponent(target)}`),
  getBoard: (id: string) => request<unknown>(`/library/boards/${encodeURIComponent(id)}`),

  listComponents: (filters?: { category?: string; use_case?: string; bus?: string }) => {
    const qs = new URLSearchParams();
    if (filters?.category) qs.set("category", filters.category);
    if (filters?.use_case) qs.set("use_case", filters.use_case);
    if (filters?.bus) qs.set("bus", filters.bus);
    const suffix = qs.size ? `?${qs.toString()}` : "";
    return request<ComponentSummary[]>(`/library/components${suffix}`);
  },
  getComponent: (id: string) => request<unknown>(`/library/components/${encodeURIComponent(id)}`),

  listModules: () => request<ModuleSummary[]>("/library/modules"),
  insertModule: (design: Design, moduleId: string) =>
    request<Design>(
      `/design/insert_module?module_id=${encodeURIComponent(moduleId)}`,
      { method: "POST", body: JSON.stringify(design) },
    ),
  seedOnboard: (design: Design) =>
    request<Design>("/design/seed_onboard", { method: "POST", body: JSON.stringify(design) }),

  listExamples: () => request<ExampleSummary[]>("/examples"),
  getExample: (id: string) => request<Design>(`/examples/${encodeURIComponent(id)}`),

  // --- Local component inventory ---
  listInventory: () => request<InventoryEntry[]>("/inventory"),
  setInventory: (
    libraryId: string,
    body: { kind?: string; quantity: number; min_quantity?: number; location?: string; note?: string },
  ) =>
    request<InventoryEntry>(`/inventory/${encodeURIComponent(libraryId)}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  deleteInventory: (libraryId: string) =>
    request<{ deleted: string }>(`/inventory/${encodeURIComponent(libraryId)}`, { method: "DELETE" }),
  checkDesignInventory: (design: Design) =>
    request<InventoryCheckResponse>("/design/inventory/check", {
      method: "POST",
      body: JSON.stringify({ design }),
    }),
  exportInventoryCsv: () => requestText("/inventory/export.csv"),
  importInventoryCsv: (csv: string) =>
    request<{ imported: number; skipped: string[] }>("/inventory/import", {
      method: "POST",
      body: JSON.stringify({ csv }),
    }),

  validate: (design: Design) =>
    request<ValidateResponse>("/design/validate", { method: "POST", body: JSON.stringify(design) }),
  render: (design: Design, opts: { strict?: boolean } = {}) =>
    request<RenderResponse>(
      `/design/render${opts.strict ? "?strict=true" : ""}`,
      { method: "POST", body: JSON.stringify(design) },
    ),
  solvePins: (design: Design) =>
    request<SolvePinsResponse>("/design/solve_pins", { method: "POST", body: JSON.stringify(design) }),
  enclosureScad: (design: Design) =>
    requestText("/design/enclosure/openscad", { method: "POST", body: JSON.stringify(design) }),
  kicadSchematic: (design: Design) =>
    requestText("/design/kicad/schematic", { method: "POST", body: JSON.stringify(design) }),
  kicadRenderStatus: () =>
    request<KicadRenderStatus>("/design/kicad/render/status"),
  kicadRender: (design: Design) =>
    requestText("/design/kicad/render", { method: "POST", body: JSON.stringify(design) }),
  kicadPcbStatus: () =>
    request<KicadPcbStatus>("/design/kicad/pcb/status"),
  kicadPcb: (design: Design) =>
    requestText("/design/kicad/pcb", { method: "POST", body: JSON.stringify(design) }),
  fabStatus: () =>
    request<FabStatus>("/design/fab/status"),
  fabBom: (design: Design) =>
    requestText("/design/fab/bom", { method: "POST", body: JSON.stringify(design) }),
  fabCpl: (design: Design) =>
    requestText("/design/fab/cpl", { method: "POST", body: JSON.stringify(design) }),
  fabPackage: (design: Design) =>
    requestBlob("/design/fab/package", { method: "POST", body: JSON.stringify(design) }),
  enclosureSearchStatus: () =>
    request<EnclosureSearchStatus>("/enclosure/search/status"),
  enclosureSearch: (params: { library_id: string; query?: string; limit?: number }) => {
    const qs = new URLSearchParams({ library_id: params.library_id });
    if (params.query) qs.set("query", params.query);
    if (params.limit != null) qs.set("limit", String(params.limit));
    return request<EnclosureSearchResponse>(`/enclosure/search?${qs.toString()}`);
  },

  agentStatus: () => request<AgentStatus>("/agent/status"),
  agentTurn: (body: { session_id?: string | null; design: Design; message: string }) =>
    request<AgentTurnResponse>("/agent/turn", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  agentSession: (id: string) =>
    request<AgentSession>(`/agent/sessions/${encodeURIComponent(id)}`),

  listSavedDesigns: () => request<SavedDesignSummary[]>("/designs"),
  getSavedDesign: (id: string) => request<Design>(`/designs/${encodeURIComponent(id)}`),
  saveDesign: (design: Design, designId?: string) =>
    request<SaveDesignResponse>("/designs", {
      method: "POST",
      body: JSON.stringify({ design, design_id: designId }),
    }),
  deleteSavedDesign: (id: string) =>
    request<{ deleted: boolean; id: string }>(`/designs/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),
  getActiveDesign: () => request<{ id: string | null }>("/designs/active"),
  setActiveDesign: (id: string | null) =>
    request<{ id: string | null }>("/designs/active", {
      method: "PUT",
      body: JSON.stringify({ id }),
    }),

  fleetStatus: () => request<FleetStatus>("/fleet/status"),
  fleetPush: (body: { design: Design; compile?: boolean; device_name?: string; strict?: boolean }) =>
    request<FleetPushResponse>("/fleet/push", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  fleetJobLog: (runId: string, offset: number) =>
    request<FleetJobLogResponse>(
      `/fleet/jobs/${encodeURIComponent(runId)}/log?offset=${offset}`,
    ),
  fleetRunStatus: (runId: string) =>
    request<FleetRunStatus>(`/fleet/jobs/${encodeURIComponent(runId)}`),

  lorawanCompileStatus: () => request<LorawanCompileStatus>("/lorawan/compile/status"),
  /** Register the device in ChirpStack and get back the band/EUIs/AppKey to
   *  write into its serial provisioning prompt. */
  lorawanProvision: (body: { dev_eui: string; design: Design }) =>
    request<LorawanProvisionResponse>("/lorawan/provision", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  /** Set the design's decodeUplink codec on the device's ChirpStack profile so
   *  uplinks decode into named fields (reflects an external GPS in lorawan.gps). */
  lorawanSetCodec: (body: { dev_eui: string; design: Design }) =>
    request<{ dev_eui: string; device_profile_id: string; codec_set: boolean }>(
      "/lorawan/codec",
      { method: "POST", body: JSON.stringify(body) },
    ),
  /** Provision a device for the ESPHome external-component path
   *  (lorawan-for-esphome). Mints an AppKey, registers the device + flushes
   *  DevNonces, and returns the keys formatted for the secrets.yaml that
   *  rides next to the rendered ESPHome config. */
  lorawanProvisionEsphome: (body: { dev_eui: string; design: Design }) =>
    request<LorawanProvisionEsphomeResponse>("/lorawan/provision-esphome", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  /** Poll ChirpStack for OTAA-join activation status. Used by the
   *  provision-esphome UI to surface the join landing. */
  lorawanActivation: (devEui: string) =>
    request<LorawanActivationResponse>(`/lorawan/activation/${encodeURIComponent(devEui)}`),
  /** Download a built firmware image by its compile cache_key. */
  lorawanFirmware: async (cacheKey: string): Promise<Uint8Array> => {
    const res = await fetch(`${API_BASE}/lorawan/firmware/${encodeURIComponent(cacheKey)}`);
    if (!res.ok) {
      let body: unknown = undefined;
      try { body = await res.json(); } catch { /* not json */ }
      throw new ApiError(res.status, `GET /lorawan/firmware/${cacheKey} -> ${res.status}`, body);
    }
    return new Uint8Array(await res.arrayBuffer());
  },
  /** Download the merged factory image (bootloader+partitions+app, flash at
   *  0x0) for blank-board flashing. 404 if the build produced no factory image. */
  lorawanFactory: async (cacheKey: string): Promise<Uint8Array> => {
    const res = await fetch(`${API_BASE}/lorawan/firmware/${encodeURIComponent(cacheKey)}/factory`);
    if (!res.ok) {
      let body: unknown = undefined;
      try { body = await res.json(); } catch { /* not json */ }
      throw new ApiError(res.status, `GET /lorawan/firmware/${cacheKey}/factory -> ${res.status}`, body);
    }
    return new Uint8Array(await res.arrayBuffer());
  },

  listUseCases: () => request<UseCaseEntry[]>("/library/use_cases"),
  recommend: (body: { query: string; limit?: number; constraints?: RecommendConstraints }) =>
    request<RecommendResponse>("/library/recommend", {
      method: "POST",
      body: JSON.stringify(body),
    }),
};

/**
 * Stream an agent turn over SSE. Yields each event as it arrives. Throws
 * ApiError on non-2xx status (e.g., 503 when the API has no ANTHROPIC_API_KEY).
 */
export async function* agentStream(body: {
  session_id?: string | null;
  design: Design;
  message: string;
}): AsyncGenerator<AgentStreamEvent> {
  const res = await fetch(`${API_BASE}/agent/stream`, {
    method: "POST",
    headers: { "content-type": "application/json", accept: "text/event-stream" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let errBody: unknown = undefined;
    try { errBody = await res.json(); } catch { /* not json */ }
    throw new ApiError(res.status, `POST /agent/stream -> ${res.status}`, errBody);
  }
  if (!res.body) {
    throw new Error("agent/stream: no response body");
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // SSE separates events by a blank line.
    let sep: number;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const block = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      for (const line of block.split("\n")) {
        if (line.startsWith("data: ")) {
          const json = line.slice(6);
          try {
            yield JSON.parse(json) as AgentStreamEvent;
          } catch {
            // ignore malformed event line
          }
        }
      }
    }
  }
}

/**
 * Stream a LoRaWAN firmware build over SSE. Yields `{type:"log"}` chunks and a
 * final `{type:"done"}` carrying the cache_key to fetch the bin with. Throws
 * ApiError on non-2xx (422 bad design / non-radio board) and Error on an
 * `event: error` frame (e.g. PlatformIO unavailable mid-build).
 */
export async function* lorawanCompile(design: Design): AsyncGenerator<LorawanCompileEvent> {
  const res = await fetch(`${API_BASE}/lorawan/compile`, {
    method: "POST",
    headers: { "content-type": "application/json", accept: "text/event-stream" },
    body: JSON.stringify(design),
  });
  if (!res.ok) {
    let errBody: unknown = undefined;
    try { errBody = await res.json(); } catch { /* not json */ }
    throw new ApiError(res.status, `POST /lorawan/compile -> ${res.status}`, errBody);
  }
  if (!res.body) {
    throw new Error("lorawan/compile: no response body");
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let sep: number;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const block = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      let isError = false;
      for (const line of block.split("\n")) {
        if (line.startsWith("event: error")) {
          isError = true;
        } else if (line.startsWith("data: ")) {
          const json = line.slice(6);
          if (isError) {
            let message = json;
            try { message = (JSON.parse(json) as { message?: string }).message ?? json; } catch { /* keep raw */ }
            throw new Error(message);
          }
          try {
            yield JSON.parse(json) as LorawanCompileEvent;
          } catch {
            // ignore malformed event line
          }
        }
      }
    }
  }
}

export { ApiError };
