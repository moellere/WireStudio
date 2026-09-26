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
  image: string | null;
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
  source: "bundled" | "user";
}

export interface ComponentCheckResponse {
  ok: boolean;
  library_id: string;
  exists: "" | "bundled" | "user";
  errors: string[];
  warnings: string[];
  unverified: string[];
  not_checked: string[];
  verified: string[];
  saved: string;
}

export interface ModuleSummary {
  id: string;
  name: string;
  category: string;
  description: string | null;
  use_cases: string[];
  component_count: number;
}

export interface ExampleSummary {
  id: string;
  name: string;
  description: string;
  board_library_id: string;
  chip_family: string;
}

export interface CompatibilityWarning {
  severity: "info" | "warn" | "error";
  code: string;
  pin: string;
  component_id: string;
  pin_role: string;
  message: string;
}

export interface RenderResponse {
  yaml: string;
  ascii: string;
  compatibility_warnings: CompatibilityWarning[];
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

export interface SolverWarning {
  level: string;
  code: string;
  text: string;
}

export interface PinAssignment {
  component_id: string;
  pin_role: string;
  old_target: Record<string, unknown>;
  new_target: Record<string, unknown>;
}

export interface SolvePinsResponse {
  design: Design;
  assigned: PinAssignment[];
  unresolved: SolverWarning[];
  warnings: SolverWarning[];
  compatibility_warnings: CompatibilityWarning[];
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

export interface SavedDesignSummary {
  id: string;
  name: string;
  description: string;
  board_library_id: string;
  chip_family: string;
  saved_at: string;
  component_count: number;
}

export interface SaveDesignResponse {
  id: string;
  saved_at: string;
}

export interface DashboardStatus {
  available: boolean;
  reason?: string | null;
  url?: string | null;
}

export interface DashboardPushResponse {
  filename: string;
  created: boolean;
  run_id?: string | null;
}

export interface DashboardRunStatus {
  run_id: string;
  filename: string;
  verdict: string; // running | passed | failed
  error: string | null;
  started_at: string;
}

export interface FleetStatus {
  available: boolean;
  reason?: string | null;
  url?: string | null;
}

export interface FleetPushResponse {
  filename: string;
  created: boolean;
  run_id?: string | null;
  enqueued: number;
}

export interface FleetJobLogResponse {
  log: string;
  offset: number;
  finished: boolean;
}

export interface FleetJobStatus {
  job_id: string;
  target: string;
  state: string;
  finished_at: string | null;
}

export interface FleetRunStatus {
  run_id: string;
  /** running | passed | failed | cancelled | unknown */
  verdict: string;
  jobs: FleetJobStatus[];
}

export interface UseCaseEntry {
  use_case: string;
  count: number;
  example_components: string[];
}

export interface Recommendation {
  library_id: string;
  name: string;
  category: string;
  use_cases: string[];
  aliases: string[];
  required_components: string[];
  current_ma_typical: number | null;
  current_ma_peak: number | null;
  vcc_min: number | null;
  vcc_max: number | null;
  score: number;
  in_examples: number;
  rationale: string;
  on_hand: number;
  parts_on_hand: number;
  parts_total: number;
  notes: string | null;
}

export interface RecommendResponse {
  query: string;
  matches: Recommendation[];
}

// --- Board parts (subcircuit expansion) -----------------------------------
export interface DesignPart {
  ref: string; // reference designator, design-global (R1, Q3)
  component_id: string;
  library_id: string;
  part_id: string | null; // null when the component maps to one symbol itself
  name: string;
  value: string;
  footprint: string;
  symbol: string;
}

export interface DesignPartsResponse {
  count: number;
  parts: DesignPart[];
}

// --- Local component inventory --------------------------------------------
export interface InventoryEntry {
  key: string; // library_id, or "part:<mpn>" for a discrete part
  library_id: string; // empty for the "part" kind
  mpn: string; // empty for the "component" / "module" kinds
  kind: string; // "component" | "module" | "part"
  quantity: number;
  min_quantity: number; // low-stock threshold; 0 = none
  low_stock: boolean;
  location: string;
  note: string;
  family: string;
  polarity: string;
  package: string;
  pinout: string;
  value: string;
  v_max: number | null;
  i_max: number | null;
}

export interface InventoryImportRejection {
  row: number; // 1-based line in the source CSV; 0 when the row parsed but the id is unknown
  reason: string;
  raw: Record<string, string>;
}

export interface InventoryImportResult {
  imported: number;
  updated: number;
  rejected: InventoryImportRejection[];
  header_row: number;
}

export interface InventoryCheckLine {
  library_id: string;
  kind: string;
  name: string;
  needed: number;
  on_hand: number;
  status: string; // "have" | "partial" | "need"
  location: string;
  note: string;
}

export interface InventorySubstitute {
  mpn: string;
  key: string;
  on_hand: number;
  location: string;
  caveats: string[];
  headroom: { v?: number | null; i?: number | null };
  rank: number;
}

export interface AppliedSubstitution {
  value: string;
  mpn: string;
  keys: string[];
  refs: string[];
  caveats: string[];
}

export interface InventoryApplyResponse {
  design: Design;
  applied: AppliedSubstitution[];
}

export interface InventoryPartCheckLine {
  value: string;
  family: string;
  refs: string[];
  needed: number;
  on_hand: number;
  status: string; // "have" | "partial" | "need" | "assumed" | "untracked"
  matched: string;
  location: string;
  substitutes: InventorySubstitute[];
  keys: string[];
  substituted_for: string[];
}

export interface PickItem {
  label: string;
  needed: number;
  on_hand: number;
  refs: string[];
  status: string;
  inventory_key: string;
}

export interface PickGroup {
  kind: "location" | "unlocated" | "assumed" | "missing";
  location: string;
  items: PickItem[];
}

export interface BuyLine {
  label: string;
  kind: string;
  family: string;
  shortfall: number;
  refs: string[];
  query: string;
  status: "ok" | "out_of_stock" | "not_found";
  note: string;
  lcsc: string;
  mfr: string;
  package: string;
  stock: number;
  price: number | null;
}

export interface BuyListResponse {
  design_id: string;
  available: boolean;
  api_url: string;
  reason: string | null;
  summary: Record<string, number>;
  lines: BuyLine[];
}

export interface InventoryCheckResponse {
  design_id: string;
  lines: InventoryCheckLine[];
  summary: Record<string, number>;
  parts: InventoryPartCheckLine[];
  parts_summary: Record<string, number>;
  pick_list: PickGroup[];
}

export interface RecommendConstraints {
  voltage?: number;
  max_current_ma_peak?: number;
  required_bus?: string;
  excluded_categories?: string[];
}

// Streaming agent events (one-of):
export type AgentStreamEvent =
  | { type: "session_start"; session_id: string }
  | { type: "text_delta"; text: string }
  | { type: "tool_use_start"; tool_use_id: string; tool: string; input: Record<string, unknown> }
  | { type: "tool_result"; tool_use_id: string; tool: string; is_error: boolean }
  | {
      type: "turn_complete";
      session_id: string;
      design: Design;
      assistant_text: string;
      tool_calls: AgentToolCall[];
      stop_reason: string;
      usage: Record<string, number>;
      model?: string;
    }
  | { type: "error"; message: string };

// ---------------------------------------------------------------------------
// Enclosure search (0.8 v2)
// ---------------------------------------------------------------------------

export interface EnclosureSourceStatus {
  source: string;
  available: boolean;
  reason: string | null;
  configure_hint: string | null;
}

export interface EnclosureSearchStatus {
  sources: EnclosureSourceStatus[];
}

export interface KicadRenderStatus {
  available: boolean;
  kicad_cli: boolean;
  skidl: boolean;
  png: boolean;
  reason: string | null;
}

export interface KicadPcbStatus {
  available: boolean;
  footprints: boolean;
  symbols: boolean;
  reason: string | null;
}

export interface KicadPcbRenderStatus {
  available: boolean;
  kicad_cli: boolean;
  libraries: boolean;
  reason: string | null;
}

export interface KicadRouteStatus {
  available: boolean;
  pcbnew: string | null;
  java: string | null;
  freerouting_jar: string | null;
  reason: string | null;
}

export type KicadRouteEvent =
  | { type: "log"; data: string }
  | { type: "done"; ok: boolean; routed: boolean; cache_key: string; cache_hit: boolean };

export interface WorkbenchStatus {
  available: boolean;
  reason: string | null;
  url: string | null;
  configure_hint: string | null;
}

export interface WorkbenchSlot {
  label: string;
  state: string;
  present: boolean;
  chip: string | null;
  product: string | null;
  serial_url: string | null;
  flapping: boolean;
  last_error: string | null;
  flashable: boolean;
  blocked_reason: string | null;
}

/** The bench buffers esptool, so every `log` arrives at completion --
 *  there is no incremental progress to render. */
export interface WorkbenchOutputLine {
  ts: number | null;
  text: string;
}

export interface WorkbenchBootCheck {
  stage: "boot" | "join";
  pattern?: string;
  proves?: string;
  matched: boolean | null;
  line?: string | null;
  via?: "buffer" | "monitor";
  timeout_s?: number;
  skipped?: string;
}

export interface WorkbenchBootResult {
  ok: boolean;
  framework: string;
  booted?: boolean;
  joined?: boolean | null;
  checks?: WorkbenchBootCheck[];
  error?: string;
}

export type WorkbenchFlashEvent =
  | { type: "log"; data: string }
  | { type: "done"; ok: boolean; slot: string; returncode: number | null };

export interface FabStatus {
  bom: boolean;
  cpl: boolean;
  gerbers: boolean;
  route: boolean;
  route_reason: string | null;
  kicad_cli: boolean;
  footprints: boolean;
  reason: string | null;
}

export interface EnclosureHit {
  source: string;
  id: string;
  title: string;
  creator: string | null;
  thumbnail_url: string | null;
  model_url: string;
  likes: number | null;
  summary: string | null;
}

export interface EnclosureSearchResponse {
  query: string;
  sources: EnclosureSourceStatus[];
  results: EnclosureHit[];
}

// --- LoRaWAN target -------------------------------------------------------

export interface LorawanCompileStatus {
  available: boolean;
  pio: string | null;
  version: string | null;
  reason: string | null;
}

/** One frame from the /lorawan/compile SSE stream. */
export type LorawanCompileEvent =
  | { type: "log"; data: string }
  | {
      type: "done";
      ok: boolean;
      cache_key: string;
      cache_hit: boolean;
      env: string;
      bin: string | null;
    };

export interface LorawanProvisionResponse {
  dev_eui: string;
  join_eui: string;
  band: string;
  sub_band: number;
  app_key: string;
  application_id: string;
  device_profile_id: string;
}

/** Response shape of GET /lorawan/chirpstack/status. `available` is the
 *  headline the UI keys off (matches the other feature-gate status
 *  endpoints). `reason` carries the gRPC status when unavailable. */
export interface ChirpstackStatus {
  available: boolean;
  url: string | null;
  reason: string | null;
}

/** Response shape of POST /lorawan/provision-esphome (W3 — external-component
 *  path). The `secrets` block is formatted for the `secrets.yaml` that rides
 *  next to the rendered ESPHome config. The AppKey is ephemeral and only
 *  appears in this response. */
export interface LorawanProvisionEsphomeResponse {
  secrets: {
    dev_eui: string;
    join_eui: string;
    app_key: string;
  };
  chirpstack: {
    application_id: string;
    device_profile_id: string;
  };
  band: string;
  sub_band: number;
}

/** Response shape of GET /lorawan/activation/{dev_eui}. `joined` flips true
 *  once the device's OTAA join lands; the other fields populate from
 *  ChirpStack's GetActivation. */
export interface LorawanActivationResponse {
  dev_eui: string;
  joined: boolean;
  dev_addr?: string;
  f_cnt_up?: number;
  n_f_cnt_down?: number;
  a_f_cnt_down?: number;
}
