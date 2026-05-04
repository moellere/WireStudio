import type {
  AgentSession,
  AgentStatus,
  AgentTurnResponse,
  BoardSummary,
  ComponentSummary,
  ExampleSummary,
  RenderResponse,
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
  render: (design: Design) =>
    request<RenderResponse>("/design/render", { method: "POST", body: JSON.stringify(design) }),
  solvePins: (design: Design) =>
    request<SolvePinsResponse>("/design/solve_pins", { method: "POST", body: JSON.stringify(design) }),

  agentStatus: () => request<AgentStatus>("/agent/status"),
  agentTurn: (body: { session_id?: string | null; design: Design; message: string }) =>
    request<AgentTurnResponse>("/agent/turn", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  agentSession: (id: string) =>
    request<AgentSession>(`/agent/sessions/${encodeURIComponent(id)}`),
};

export { ApiError };
