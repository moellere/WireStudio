/**
 * Component tests for CapabilityPickerDialog. Focused on the surface
 * with state machinery: the alternatives disclosure (one open at a
 * time, score delta sign + emerald tint when an alternative beats
 * the row's score) and the bus filter's hide-then-show transition.
 *
 * The recommend / use_cases endpoints are mocked at the api boundary;
 * we don't exercise the network or the recommender ranker here.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { CapabilityPickerDialog } from "./CapabilityPickerDialog";
import { api } from "../api/client";
import type { Recommendation } from "../types/api";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ...actual,
    api: {
      ...actual.api,
      listUseCases: vi.fn(),
      recommend: vi.fn(),
    },
  };
});

const mockApi = api as unknown as {
  listUseCases: ReturnType<typeof vi.fn>;
  recommend: ReturnType<typeof vi.fn>;
};

function recommendation(over: Partial<Recommendation>): Recommendation {
  return {
    library_id: over.library_id ?? "x",
    name: over.name ?? "X",
    category: over.category ?? "sensor",
    use_cases: over.use_cases ?? [],
    aliases: over.aliases ?? [],
    required_components: over.required_components ?? [],
    current_ma_typical: over.current_ma_typical ?? null,
    current_ma_peak: over.current_ma_peak ?? null,
    vcc_min: over.vcc_min ?? null,
    vcc_max: over.vcc_max ?? null,
    score: over.score ?? 0,
    in_examples: over.in_examples ?? 0,
    rationale: over.rationale ?? "",
    notes: over.notes ?? null,
  };
}

beforeEach(() => {
  mockApi.listUseCases.mockReset();
  mockApi.recommend.mockReset();
  mockApi.listUseCases.mockResolvedValue([
    { use_case: "temperature", count: 1, example_components: ["bme280"] },
  ]);
});

describe("alternatives disclosure", () => {
  it("renders an N-alternatives toggle for every match when there are multiple", async () => {
    mockApi.recommend.mockResolvedValue({
      query: "temperature",
      matches: [
        recommendation({ library_id: "bme280", name: "BME280", score: 12 }),
        recommendation({ library_id: "dht22", name: "DHT22", score: 8 }),
        recommendation({ library_id: "ds18b20", name: "DS18B20", score: 6 }),
      ],
    });
    render(
      <CapabilityPickerDialog
        designReady
        designBusTypes={[]}
        onAdd={async () => {}}
        onClose={() => {}}
      />,
    );

    // Pick the temperature capability on the left to trigger recommend.
    await waitFor(() => screen.getByText("temperature"));
    await userEvent.click(screen.getByText("temperature"));

    // Three rows -> each one has "2 alternatives" (the other two).
    await waitFor(() => {
      expect(screen.getAllByText(/2 alternatives/i).length).toBe(3);
    });
  });

  it("expands a single row at a time and shows the score delta with sign", async () => {
    mockApi.recommend.mockResolvedValue({
      query: "temperature",
      matches: [
        recommendation({ library_id: "bme280", name: "BME280", score: 12 }),
        recommendation({ library_id: "dht22", name: "DHT22", score: 8 }),
      ],
    });
    render(
      <CapabilityPickerDialog
        designReady
        designBusTypes={[]}
        onAdd={async () => {}}
        onClose={() => {}}
      />,
    );
    await waitFor(() => screen.getByText("temperature"));
    await userEvent.click(screen.getByText("temperature"));
    await waitFor(() => screen.getByText("BME280"));

    // Expand the top row (BME280, score 12). The collapsed-state toggle
    // text is "▸ 1 alternative"; clicking it flips to "▾".
    const toggles = screen.getAllByRole("button", { name: /1 alternative/i });
    await userEvent.click(toggles[0]);

    // The expanded panel lists the OTHER match (DHT22) with the score
    // delta. -4 < 0 so the delta should render in the muted (zinc-600)
    // colour, not emerald.
    const delta = screen.getByText(/\(-4\.0\)/);
    expect(delta).toBeInTheDocument();
    expect(delta).toHaveClass("text-zinc-600");
  });

  it("collapses the previously expanded row when a new one is opened", async () => {
    mockApi.recommend.mockResolvedValue({
      query: "temperature",
      matches: [
        recommendation({ library_id: "bme280", name: "BME280", score: 12 }),
        recommendation({ library_id: "dht22", name: "DHT22", score: 8 }),
      ],
    });
    render(
      <CapabilityPickerDialog
        designReady
        designBusTypes={[]}
        onAdd={async () => {}}
        onClose={() => {}}
      />,
    );
    await waitFor(() => screen.getByText("temperature"));
    await userEvent.click(screen.getByText("temperature"));
    await waitFor(() => screen.getByText("BME280"));

    const toggles = screen.getAllByRole("button", { name: /1 alternative/i });
    await userEvent.click(toggles[0]);
    await userEvent.click(toggles[1]);

    // Only one toggle reports aria-expanded=true at any time.
    const expanded = toggles.filter(
      (b) => b.getAttribute("aria-expanded") === "true",
    );
    expect(expanded).toHaveLength(1);
    // And it's the second one (DHT22's alternatives panel).
    expect(expanded[0]).toBe(toggles[1]);
  });

  it("uses an emerald-tinted delta when the alternative beats the row's score", async () => {
    // This case is contrived (the recommender returns sorted-desc), but the
    // UI doesn't *enforce* sort order, so the rendering branch is real.
    mockApi.recommend.mockResolvedValue({
      query: "temperature",
      matches: [
        recommendation({ library_id: "low", name: "Low", score: 5 }),
        recommendation({ library_id: "high", name: "High", score: 10 }),
      ],
    });
    render(
      <CapabilityPickerDialog
        designReady
        designBusTypes={[]}
        onAdd={async () => {}}
        onClose={() => {}}
      />,
    );
    await waitFor(() => screen.getByText("temperature"));
    await userEvent.click(screen.getByText("temperature"));
    await waitFor(() => screen.getByText("Low"));

    // Expand the first (Low, 5) row. Its alternative is High (10), delta +5.
    const toggles = screen.getAllByRole("button", { name: /1 alternative/i });
    await userEvent.click(toggles[0]);
    const delta = screen.getByText(/\(\+5\.0\)/);
    expect(delta).toBeInTheDocument();
    expect(delta).toHaveClass("text-emerald-300");
  });
});

describe("bus filter integration", () => {
  it("hides matches that need a bus the design lacks and surfaces a counter", async () => {
    mockApi.recommend.mockResolvedValue({
      query: "temperature",
      matches: [
        recommendation({
          library_id: "bme280", name: "BME280", score: 12,
          required_components: ["i2c", "decoupling_caps"],
        }),
        recommendation({
          library_id: "spi-temp", name: "SPI Temp", score: 9,
          required_components: ["spi"],
        }),
      ],
    });
    render(
      <CapabilityPickerDialog
        designReady
        designBusTypes={["i2c"]}
        onAdd={async () => {}}
        onClose={() => {}}
      />,
    );
    await waitFor(() => screen.getByText("temperature"));
    await userEvent.click(screen.getByText("temperature"));
    await waitFor(() => screen.getByText("BME280"));

    // SPI part filtered out, hidden-counter shown, BME280 still listed.
    expect(screen.queryByText("SPI Temp")).not.toBeInTheDocument();
    expect(screen.getByText(/1 hidden by the bus filter/i)).toBeInTheDocument();
  });

  it("re-shows hidden matches when the user unchecks the filter", async () => {
    mockApi.recommend.mockResolvedValue({
      query: "temperature",
      matches: [
        recommendation({
          library_id: "spi-temp", name: "SPI Temp", score: 9,
          required_components: ["spi"],
        }),
      ],
    });
    render(
      <CapabilityPickerDialog
        designReady
        designBusTypes={["i2c"]}
        onAdd={async () => {}}
        onClose={() => {}}
      />,
    );
    await waitFor(() => screen.getByText("temperature"));
    await userEvent.click(screen.getByText("temperature"));
    await waitFor(() =>
      screen.getByText(/1 match.*hidden by the bus filter/i),
    );

    const checkbox = screen.getByRole("checkbox", { name: /match my buses/i });
    await userEvent.click(checkbox);
    expect(screen.getByText("SPI Temp")).toBeInTheDocument();
  });
});

describe("Add interaction", () => {
  it("calls onAdd with the library_id and shows the Added affirmation", async () => {
    mockApi.recommend.mockResolvedValue({
      query: "temperature",
      matches: [recommendation({ library_id: "bme280", name: "BME280", score: 12 })],
    });
    const onAdd = vi.fn().mockResolvedValue(undefined);
    render(
      <CapabilityPickerDialog
        designReady
        designBusTypes={[]}
        onAdd={onAdd}
        onClose={() => {}}
      />,
    );
    await waitFor(() => screen.getByText("temperature"));
    await userEvent.click(screen.getByText("temperature"));
    await waitFor(() => screen.getByText("BME280"));

    const row = screen.getByText("BME280").closest("li") as HTMLElement;
    const addButton = within(row).getByRole("button", { name: /^Add$/ });
    await userEvent.click(addButton);

    expect(onAdd).toHaveBeenCalledWith("bme280");
    await waitFor(() =>
      expect(within(row).getByText(/Added/)).toBeInTheDocument(),
    );
  });
});
