// Wire types matching studio/api/schemas.py + studio/library.py + studio/model.py.
// Hand-curated to keep the dependency one-way (UI knows about API, not vice
// versa). When the Python schema changes, update these.

export interface BoardSummary {
  id: string;
  name: string;
  mcu: string;
  chip_variant: string;
  framework: string;
  platformio_board: string;
  flash_size_mb: number | null;
  rail_names: string[];
}

export interface ComponentSummary {
  id: string;
  name: string;
  category: string;
  use_cases: string[];
  aliases: string[];
  required_components: string[];
  current_ma_typical: number | null;
  current_ma_peak: number | null;
}

export interface ExampleSummary {
  id: string;
  name: string;
  description: string;
  board_library_id: string;
  chip_family: string;
}

export interface RenderResponse {
  yaml: string;
  ascii: string;
}

export interface DesignWarning {
  level: "info" | "warn" | "error";
  code: string;
  text: string;
}

export interface ValidateResponse {
  ok: boolean;
  design_id: string;
  name: string;
  component_count: number;
  bus_count: number;
  connection_count: number;
  warnings: DesignWarning[];
}

// design.json is opaque on the wire; the UI reads/writes specific fields it
// cares about (id, name, board) but otherwise treats it as a plain JSON value.
export type Design = Record<string, unknown>;

export interface AgentStatus {
  available: boolean;
  reason: string | null;
}

export interface AgentToolCall {
  tool: string;
  input: Record<string, unknown>;
  is_error: boolean;
}

export interface AgentTurnResponse {
  session_id: string;
  design: Design;
  assistant_text: string;
  tool_calls: AgentToolCall[];
  stop_reason: string;
  usage: Record<string, number>;
}

export interface AgentSessionMessage {
  role: string;
  content: string;
  timestamp: string;
}

export interface AgentSession {
  session_id: string;
  messages: AgentSessionMessage[];
}
