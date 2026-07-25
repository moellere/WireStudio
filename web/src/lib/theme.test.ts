import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { useTheme } from "./theme";

const KEY = "wirestudio:ui:theme";

beforeEach(() => {
  window.localStorage.clear();
  delete document.documentElement.dataset.theme;
});

afterEach(() => {
  window.localStorage.clear();
  delete document.documentElement.dataset.theme;
});

describe("useTheme", () => {
  it("defaults to dark when nothing is stored and no light preference", () => {
    const { result } = renderHook(() => useTheme());
    expect(result.current[0]).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("hydrates from localStorage", () => {
    window.localStorage.setItem(KEY, "light");
    const { result } = renderHook(() => useTheme());
    expect(result.current[0]).toBe("light");
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("persists changes and stamps the html element", () => {
    const { result } = renderHook(() => useTheme());
    act(() => result.current[1]("light"));
    expect(window.localStorage.getItem(KEY)).toBe("light");
    expect(document.documentElement.dataset.theme).toBe("light");
    act(() => result.current[1]("dark"));
    expect(window.localStorage.getItem(KEY)).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("ignores invalid stored values", () => {
    window.localStorage.setItem(KEY, "sepia");
    const { result } = renderHook(() => useTheme());
    expect(result.current[0]).toBe("dark");
  });
});
