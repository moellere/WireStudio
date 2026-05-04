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
import { api } from "../api/client";
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
    },
  };
});

const mockApi = api as unknown as {
  fleetStatus: ReturnType<typeof vi.fn>;
  fleetPush: ReturnType<typeof vi.fn>;
  fleetJobLog: ReturnType<typeof vi.fn>;
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
  mockApi.fleetStatus.mockReset();
  mockApi.fleetPush.mockReset();
  mockApi.fleetJobLog.mockReset();
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
