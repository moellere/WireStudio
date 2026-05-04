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
  FleetStatus,
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

export const api = {
  health: () => request<{ ok: boolean; version: string }>("/health"),

  listBoards: () => request<BoardSummary[]>("/library/boards"),
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

  listExamples: () => request<ExampleSummary[]>("/examples"),
  getExample: (id: string) => request<Design>(`/examples/${encodeURIComponent(id)}`),

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

export { ApiError };
