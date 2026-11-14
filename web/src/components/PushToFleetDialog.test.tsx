/**
 * Component tests for PushToFleetDialog. Two surfaces:
 *
 *   1. Status fetch on mount + the canPush gating that follows from it.
 *   2. The build-log polling loop. The single-shot "first chunk finishes
 *      the job" path is covered without timers; the multi-chunk path uses
 *      vi.useFakeTimers to step over the 1.5s between polls deterministically.
 *
 * The api/client surface is mocked at the import boundary; we never make a
 * real network call.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { PushToFleetDialog } from "./PushToFleetDialog";
import { api, ApiError } from "../api/client";
import type { Design } from "../types/api";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ...actual,
    api: {
      ...actual.api,
      fleetStatus: vi.fn(),
      fleetPush: vi.fn(),
      fleetJobLog: vi.fn(),
      fleetRunStatus: vi.fn(),
      esphomeRepoStatus: vi.fn(),
      esphomeRepoPush: vi.fn(),
      esphomeDashboardStatus: vi.fn(),
      esphomeDashboardPush: vi.fn(),
      esphomeDashboardJobLog: vi.fn(),
      esphomeDashboardRunStatus: vi.fn(),
      esphomeDashboardFirmware: vi.fn(),
    },
  };
});

const flashFirmware = vi.hoisted(() => vi.fn());
vi.mock("../lib/flash", () => ({ flashFirmware }));

const mockApi = api as unknown as {
  fleetStatus: ReturnType<typeof vi.fn>;
  fleetPush: ReturnType<typeof vi.fn>;
  fleetJobLog: ReturnType<typeof vi.fn>;
  fleetRunStatus: ReturnType<typeof vi.fn>;
  esphomeRepoStatus: ReturnType<typeof vi.fn>;
  esphomeRepoPush: ReturnType<typeof vi.fn>;
  esphomeDashboardStatus: ReturnType<typeof vi.fn>;
  esphomeDashboardPush: ReturnType<typeof vi.fn>;
  esphomeDashboardJobLog: ReturnType<typeof vi.fn>;
  esphomeDashboardRunStatus: ReturnType<typeof vi.fn>;
  esphomeDashboardFirmware: ReturnType<typeof vi.fn>;
};

const design: Design = {
  schema_version: "0.1",
  id: "garage-motion",
  name: "Garage motion",
  board: { library_id: "esp32-devkitc-v4", mcu: "esp32" },
  components: [],
  buses: [],
  connections: [],
  requirements: [],
  warnings: [],
  fleet: { device_name: "garage-motion", tags: [] },
} as Design;

beforeEach(() => {
  mockApi.esphomeRepoStatus.mockReset().mockResolvedValue({ available: false, reason: "ESPHOME_REPO and ESPHOME_REPO_TOKEN not set" });
  mockApi.esphomeRepoPush.mockReset();
  mockApi.esphomeDashboardStatus.mockReset().mockResolvedValue({ available: false, reason: "ESPHOME_DASHBOARD_URL not set", url: null });
  mockApi.esphomeDashboardPush.mockReset();
  mockApi.esphomeDashboardJobLog.mockReset();
  mockApi.esphomeDashboardRunStatus.mockReset();
  mockApi.esphomeDashboardFirmware.mockReset();
  flashFirmware.mockReset();
  mockApi.fleetStatus.mockReset();
  mockApi.fleetPush.mockReset();
  mockApi.fleetJobLog.mockReset();
  mockApi.fleetRunStatus.mockReset();
});

describe("status + push gating", () => {
  it("disables Push when the fleet is unconfigured", async () => {
    mockApi.fleetStatus.mockResolvedValue({
      available: false,
      reason: "FLEET_URL not set",
      url: null,
    });
    render(<PushToFleetDialog design={design} onClose={() => {}} />);
    const pushButton = await screen.findByRole("button", { name: /^Push/i });
    expect(pushButton).toBeDisabled();
    expect(screen.getByText(/FLEET_URL not set/i)).toBeInTheDocument();
  });

  it("enables Push when configured + fires fleetPush with the device name", async () => {
    mockApi.fleetStatus.mockResolvedValue({ available: true, reason: null, url: "http://addon" });
    mockApi.fleetPush.mockResolvedValue({
      filename: "garage-motion.yaml",
      created: true,
      run_id: null,
      enqueued: 0,
    });
    render(<PushToFleetDialog design={design} onClose={() => {}} />);
    const pushButton = await screen.findByRole("button", { name: /^Push/i });
    await waitFor(() => expect(pushButton).not.toBeDisabled());
    await userEvent.click(pushButton);
    await waitFor(() =>
      expect(screen.getByText(/Created/i)).toBeInTheDocument(),
    );
    expect(mockApi.fleetPush).toHaveBeenCalledWith(
      expect.objectContaining({ design, compile: false, device_name: "garage-motion" }),
    );
  });
});

describe("build-log polling", () => {
  it("does not render the log viewer when the push response has no run_id", async () => {
    mockApi.fleetStatus.mockResolvedValue({ available: true, reason: null, url: "http://addon" });
    mockApi.fleetPush.mockResolvedValue({
      filename: "garage-motion.yaml",
      created: true,
      run_id: null,
      enqueued: 0,
    });
    render(<PushToFleetDialog design={design} onClose={() => {}} />);
    const btn = await screen.findByRole("button", { name: /^Push/i });
    await waitFor(() => expect(btn).not.toBeDisabled());
    await userEvent.click(btn);
    await screen.findByText(/Created/i);
    expect(screen.queryByText(/build log/i)).not.toBeInTheDocument();
    expect(mockApi.fleetJobLog).not.toHaveBeenCalled();
  });

  it("tails a single-shot finished log without needing the timer", async () => {
    mockApi.fleetStatus.mockResolvedValue({ available: true, reason: null, url: "http://addon" });
    mockApi.fleetPush.mockResolvedValue({
      filename: "garage-motion.yaml",
      created: false,
      run_id: "run-42",
      enqueued: 1,
    });
    mockApi.fleetJobLog.mockResolvedValueOnce({
      log: "build ok\n",
      offset: 9,
      finished: true,
    });
    render(<PushToFleetDialog design={design} onClose={() => {}} />);
    const pushBtn = await screen.findByRole("button", { name: /^Push/i });
    await waitFor(() => expect(pushBtn).not.toBeDisabled());

    // Tick the compile checkbox so the user-visible state matches the
    // run_id-bearing response we mocked.
    await userEvent.click(screen.getByRole("checkbox", { name: /compile after upload/i }));
    await userEvent.click(pushBtn);

    await waitFor(() => screen.getByText(/Compile enqueued/i));
    await waitFor(() => screen.getByText(/build ok/));
    expect(screen.getByText(/finished/i)).toBeInTheDocument();
    expect(mockApi.fleetJobLog).toHaveBeenCalledWith("run-42", 0);
    // Polling stops once finished; only one call.
    expect(mockApi.fleetJobLog).toHaveBeenCalledTimes(1);
  });

  it("shows the compile verdict once the log finishes", async () => {
    mockApi.fleetStatus.mockResolvedValue({ available: true, reason: null, url: "http://addon" });
    mockApi.fleetPush.mockResolvedValue({
      filename: "garage-motion.yaml",
      created: false,
      run_id: "run-v",
      enqueued: 1,
    });
    mockApi.fleetJobLog.mockResolvedValueOnce({ log: "build ok\n", offset: 9, finished: true });
    mockApi.fleetRunStatus.mockResolvedValue({
      run_id: "run-v",
      verdict: "passed",
      jobs: [{ job_id: "j1", target: "garage-motion.yaml", state: "success", finished_at: null }],
    });
    render(<PushToFleetDialog design={design} onClose={() => {}} />);
    const pushBtn = await screen.findByRole("button", { name: /^Push/i });
    await waitFor(() => expect(pushBtn).not.toBeDisabled());
    await userEvent.click(screen.getByRole("checkbox", { name: /compile after upload/i }));
    await userEvent.click(pushBtn);

    await waitFor(() => screen.getByText(/build ok/));
    await waitFor(() => expect(mockApi.fleetRunStatus).toHaveBeenCalledWith("run-v"));
    await waitFor(() => screen.getByText(/Compile passed/));
  });
});

describe("build-log SSE transport", () => {
  // A minimal EventSource stub: tests reach in and call the captured
  // onmessage / addEventListener handlers to drive the dialog through
  // the streaming path without a real network connection.
  type Listener = (ev: MessageEvent) => void;
  class FakeEventSource {
    static instances: FakeEventSource[] = [];
    static OPEN = 1;
    static CLOSED = 2;
    url: string;
    readyState = FakeEventSource.OPEN;
    onmessage: ((ev: MessageEvent) => void) | null = null;
    onerror: (() => void) | null = null;
    listeners: Record<string, Listener[]> = {};
    constructor(url: string) {
      this.url = url;
      FakeEventSource.instances.push(this);
    }
    addEventListener(name: string, cb: Listener) {
      (this.listeners[name] ??= []).push(cb);
    }
    close() { this.readyState = FakeEventSource.CLOSED; }
    emitMessage(payload: object) {
      this.onmessage?.({ data: JSON.stringify(payload) } as MessageEvent);
    }
    emitNamed(name: string, data: object) {
      const ev = { data: JSON.stringify(data) } as MessageEvent;
      (this.listeners[name] ?? []).forEach((cb) => cb(ev));
    }
  }

  beforeEach(() => {
    FakeEventSource.instances = [];
    (globalThis as unknown as { EventSource: typeof FakeEventSource }).EventSource =
      FakeEventSource;
  });
  afterEach(() => {
    delete (globalThis as { EventSource?: unknown }).EventSource;
  });

  it("streams chunks via EventSource and stops on the done event", async () => {
    mockApi.fleetStatus.mockResolvedValue({ available: true, reason: null, url: "http://addon" });
    mockApi.fleetPush.mockResolvedValue({
      filename: "garage-motion.yaml",
      created: false,
      run_id: "run-77",
      enqueued: 1,
    });
    render(<PushToFleetDialog design={design} onClose={() => {}} />);
    const pushBtn = await screen.findByRole("button", { name: /^Push/i });
    await waitFor(() => expect(pushBtn).not.toBeDisabled());
    await userEvent.click(screen.getByRole("checkbox", { name: /compile after upload/i }));
    await userEvent.click(pushBtn);

    await waitFor(() => expect(FakeEventSource.instances.length).toBe(1));
    const es = FakeEventSource.instances[0];
    expect(es.url).toMatch(/\/api\/fleet\/jobs\/run-77\/log\/stream/);

    es.emitMessage({ log: "compiling...\n", offset: 13, finished: false });
    await waitFor(() => screen.getByText(/compiling\.\.\./));
    expect(screen.getByText(/tailing.*\(stream\)/i)).toBeInTheDocument();

    es.emitMessage({ log: "build ok\n", offset: 22, finished: true });
    await waitFor(() => screen.getByText(/build ok/));
    await waitFor(() => screen.getByText(/finished/i));
    // The polling endpoint stays untouched -- SSE handled the run.
    expect(mockApi.fleetJobLog).not.toHaveBeenCalled();
  });

  it("falls back to HTTP polling on a transport error", async () => {
    mockApi.fleetStatus.mockResolvedValue({ available: true, reason: null, url: "http://addon" });
    mockApi.fleetPush.mockResolvedValue({
      filename: "garage-motion.yaml",
      created: false,
      run_id: "run-88",
      enqueued: 1,
    });
    mockApi.fleetJobLog.mockResolvedValueOnce({
      log: "fallback ok\n", offset: 12, finished: true,
    });
    render(<PushToFleetDialog design={design} onClose={() => {}} />);
    const pushBtn = await screen.findByRole("button", { name: /^Push/i });
    await waitFor(() => expect(pushBtn).not.toBeDisabled());
    await userEvent.click(screen.getByRole("checkbox", { name: /compile after upload/i }));
    await userEvent.click(pushBtn);

    await waitFor(() => expect(FakeEventSource.instances.length).toBe(1));
    const es = FakeEventSource.instances[0];
    // Simulate a transport hiccup: onerror fires while readyState is OPEN.
    es.onerror?.();

    await waitFor(() => expect(mockApi.fleetJobLog).toHaveBeenCalledTimes(1));
    await waitFor(() => screen.getByText(/fallback ok/));
    await waitFor(() => screen.getByText(/finished/i));
    expect(screen.queryByText(/\(stream\)/i)).not.toBeInTheDocument();
  });

  it("surfaces a server-emitted error event without falling back", async () => {
    mockApi.fleetStatus.mockResolvedValue({ available: true, reason: null, url: "http://addon" });
    mockApi.fleetPush.mockResolvedValue({
      filename: "garage-motion.yaml",
      created: false,
      run_id: "run-bad",
      enqueued: 1,
    });
    render(<PushToFleetDialog design={design} onClose={() => {}} />);
    const pushBtn = await screen.findByRole("button", { name: /^Push/i });
    await waitFor(() => expect(pushBtn).not.toBeDisabled());
    await userEvent.click(screen.getByRole("checkbox", { name: /compile after upload/i }));
    await userEvent.click(pushBtn);

    await waitFor(() => expect(FakeEventSource.instances.length).toBe(1));
    const es = FakeEventSource.instances[0];
    es.emitNamed("error", { message: "unknown run_id 'run-bad'" });

    await waitFor(() => screen.getByText(/log error: unknown run_id/i));
    // Server-side logical error does NOT trigger the polling fallback.
    expect(mockApi.fleetJobLog).not.toHaveBeenCalled();
  });
});

describe("build-log multi-chunk polling", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("appends chunks and stops when finished=true", async () => {
    mockApi.fleetStatus.mockResolvedValue({ available: true, reason: null, url: "http://addon" });
    mockApi.fleetPush.mockResolvedValue({
      filename: "garage-motion.yaml",
      created: false,
      run_id: "run-99",
      enqueued: 1,
    });
    mockApi.fleetJobLog
      .mockResolvedValueOnce({ log: "compiling...\n", offset: 13, finished: false })
      .mockResolvedValueOnce({ log: "linking...\n", offset: 24, finished: true });

    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTimeAsync });
    render(<PushToFleetDialog design={design} onClose={() => {}} />);
    const pushBtn = await screen.findByRole("button", { name: /^Push/i });
    await waitFor(() => expect(pushBtn).not.toBeDisabled());
    await user.click(screen.getByRole("checkbox", { name: /compile after upload/i }));
    await user.click(pushBtn);

    // First chunk lands without needing the timer (it resolves before the
    // setTimeout(1500) gate).
    await waitFor(() => screen.getByText(/compiling\.\.\./));
    expect(mockApi.fleetJobLog).toHaveBeenNthCalledWith(1, "run-99", 0);
    expect(screen.getByText(/tailing…/)).toBeInTheDocument();

    // Cross the 1.5s poll gap; the second chunk fetches at offset=13.
    await vi.advanceTimersByTimeAsync(1500);
    await waitFor(() => screen.getByText(/linking\.\.\./));
    expect(mockApi.fleetJobLog).toHaveBeenNthCalledWith(2, "run-99", 13);
    await waitFor(() => screen.getByText(/finished/i));
    expect(mockApi.fleetJobLog).toHaveBeenCalledTimes(2);
  });

  it("surfaces a log error and stops polling when fleetJobLog throws", async () => {
    mockApi.fleetStatus.mockResolvedValue({ available: true, reason: null, url: "http://addon" });
    mockApi.fleetPush.mockResolvedValue({
      filename: "garage-motion.yaml",
      created: false,
      run_id: "run-7",
      enqueued: 1,
    });
    mockApi.fleetJobLog.mockRejectedValueOnce(new Error("addon disconnected"));

    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTimeAsync });
    render(<PushToFleetDialog design={design} onClose={() => {}} />);
    const pushBtn = await screen.findByRole("button", { name: /^Push/i });
    await waitFor(() => expect(pushBtn).not.toBeDisabled());
    await user.click(screen.getByRole("checkbox", { name: /compile after upload/i }));
    await user.click(pushBtn);

    await waitFor(() => screen.getByText(/log error: addon disconnected/i));
    expect(screen.getByText(/stopped/i)).toBeInTheDocument();
    expect(mockApi.fleetJobLog).toHaveBeenCalledTimes(1);
  });
});


describe("ESPHome dashboard build path", () => {
  it("defaults to the dashboard when only it is configured and pushes there", async () => {
    mockApi.fleetStatus.mockResolvedValue({ available: false, reason: "FLEET_URL not set", url: null });
    mockApi.esphomeDashboardStatus.mockResolvedValue({ available: true, reason: null, url: "http://ha:6052" });
    mockApi.esphomeDashboardPush.mockResolvedValue({ filename: "garage-motion.yaml", created: true, run_id: null });
    render(<PushToFleetDialog design={design} onClose={vi.fn()} />);
    await waitFor(() => expect(screen.getByText(/connected · http:\/\/ha:6052/)).toBeInTheDocument());
    expect(screen.getByRole("radio", { name: /ESPHome dashboard/i })).toHaveAttribute("aria-checked", "true");
    await userEvent.click(screen.getByRole("button", { name: /push/i }));
    await waitFor(() => expect(mockApi.esphomeDashboardPush).toHaveBeenCalled());
    expect(mockApi.fleetPush).not.toHaveBeenCalled();
    expect(mockApi.esphomeDashboardPush.mock.calls[0][0]).toMatchObject({ compile: false, device_name: "garage-motion" });
  });

  it("offers a picker when several dashboards are configured and pushes to the chosen one", async () => {
    mockApi.fleetStatus.mockResolvedValue({ available: false, reason: "FLEET_URL not set", url: null });
    mockApi.esphomeDashboardStatus.mockResolvedValue({
      available: true, reason: null, url: "http://ha:6052",
      targets: [
        { name: "ha", label: "Home Assistant", url: "http://ha:6052", available: true, reason: null, default: true },
        { name: "cluster", label: "Cluster builder", url: "http://cluster:6052", available: true, reason: null, default: false },
      ],
    });
    mockApi.esphomeDashboardPush.mockResolvedValue({ filename: "garage-motion.yaml", created: true, run_id: null, target: "cluster" });
    render(<PushToFleetDialog design={design} onClose={vi.fn()} />);
    const picker = await screen.findByRole("combobox", { name: "Dashboard" });
    expect(picker).toHaveValue("ha");
    expect(screen.getByText(/connected · http:\/\/ha:6052/)).toBeInTheDocument();
    await userEvent.selectOptions(picker, "cluster");
    expect(screen.getByText(/connected · http:\/\/cluster:6052/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /push/i }));
    await waitFor(() => expect(mockApi.esphomeDashboardPush).toHaveBeenCalled());
    expect(mockApi.esphomeDashboardPush.mock.calls[0][0]).toMatchObject({ target: "cluster" });
    expect(await screen.findByText(/on Cluster builder\./)).toBeInTheDocument();
  });

  it("flashes the image a passed compile built", async () => {
    mockApi.fleetStatus.mockResolvedValue({ available: false, reason: "FLEET_URL not set", url: null });
    mockApi.esphomeDashboardStatus.mockResolvedValue({ available: true, reason: null, url: "http://ha:6052" });
    mockApi.esphomeDashboardPush.mockResolvedValue({ filename: "garage-motion.yaml", created: true, run_id: "r1" });
    mockApi.esphomeDashboardJobLog.mockResolvedValue({ log: "[SUCCESS]\n", offset: 10, finished: true });
    mockApi.esphomeDashboardRunStatus.mockResolvedValue({ run_id: "r1", filename: "garage-motion.yaml", verdict: "passed", error: null, started_at: "" });
    const image = new Uint8Array([0xe9, 1, 2, 3]);
    mockApi.esphomeDashboardFirmware.mockResolvedValue(image);
    flashFirmware.mockResolvedValue({ close: vi.fn().mockResolvedValue(undefined) });
    render(<PushToFleetDialog design={design} onClose={vi.fn()} />);
    await waitFor(() => expect(screen.getByText(/connected · http:\/\/ha:6052/)).toBeInTheDocument());
    await userEvent.click(screen.getByRole("checkbox"));
    await userEvent.click(screen.getByRole("button", { name: /push & compile/i }));
    await userEvent.click(await screen.findByRole("button", { name: "Flash over USB" }));
    await waitFor(() => expect(screen.getByText(/Wrote 4 bytes/)).toBeInTheDocument());
    expect(mockApi.esphomeDashboardFirmware).toHaveBeenCalledWith("r1", { factory: true });
    expect(flashFirmware.mock.calls[0][0]).toMatchObject({ images: [{ data: image, address: 0 }], eraseAll: true });
  });

  it("switching the build path re-probes its status", async () => {
    mockApi.fleetStatus.mockResolvedValue({ available: true, reason: null, url: "http://addon" });
    mockApi.esphomeDashboardStatus.mockResolvedValue({ available: false, reason: "ESPHOME_DASHBOARD_URL not set", url: null });
    render(<PushToFleetDialog design={design} onClose={vi.fn()} />);
    await waitFor(() => expect(screen.getByText(/connected · http:\/\/addon/)).toBeInTheDocument());
    await userEvent.click(screen.getByRole("radio", { name: /ESPHome dashboard/i }));
    await waitFor(() => expect(screen.getByText(/ESPHOME_DASHBOARD_URL not set/)).toBeInTheDocument());
    expect(screen.getByText(/Set/).textContent).toContain("ESPHOME_DASHBOARD_URL");
  });
});

describe("ESPHome repo path", () => {
  it("commits without compiling and asks before replacing a hand-written file", async () => {
    mockApi.fleetStatus.mockResolvedValue({ available: false, reason: "FLEET_URL not set", url: null });
    mockApi.esphomeRepoStatus.mockResolvedValue({
      available: true, reason: null, repo: "me/esphome", branch: "main", url: "https://github.com/me/esphome/tree/main",
    });
    mockApi.esphomeRepoPush
      .mockRejectedValueOnce(new ApiError(409, "Conflict", {
        detail: { error: "file_exists", message: "garage-motion.yaml is already in me/esphome and was last changed outside WireStudio" },
      }))
      .mockResolvedValueOnce({
        filename: "garage-motion.yaml", created: false, changed: true, commit: "0123456789abcdef",
        url: "https://github.com/me/esphome/blob/main/garage-motion.yaml",
      });
    render(<PushToFleetDialog design={design} onClose={vi.fn()} />);
    await waitFor(() => expect(screen.getByText(/connected · https:\/\/github.com\/me\/esphome/)).toBeInTheDocument());
    expect(screen.getByRole("radio", { name: /ESPHome repo/i })).toHaveAttribute("aria-checked", "true");
    expect(screen.queryByText(/Compile after upload/)).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /push/i }));
    await waitFor(() => expect(screen.getByText(/is already in me\/esphome/)).toBeInTheDocument());
    expect(mockApi.esphomeRepoPush.mock.calls[0][0]).toMatchObject({ device_name: "garage-motion", overwrite: false });

    await userEvent.click(screen.getByRole("checkbox", { name: /Replace an existing file/i }));
    await userEvent.click(screen.getByRole("button", { name: /push/i }));
    await waitFor(() => expect(screen.getByText(/Committed an update to/)).toBeInTheDocument());
    expect(mockApi.esphomeRepoPush.mock.calls[1][0]).toMatchObject({ overwrite: true });
    expect(screen.getByRole("link", { name: "garage-motion.yaml" })).toHaveAttribute(
      "href", "https://github.com/me/esphome/blob/main/garage-motion.yaml");
    expect(screen.getByText(/0123456/)).toBeInTheDocument();
  });
});
