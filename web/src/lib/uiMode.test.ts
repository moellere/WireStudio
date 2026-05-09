import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { useAdvancedMode } from "./uiMode";

const KEY = "wirestudio:ui:advanced";

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  window.localStorage.clear();
});

describe("useAdvancedMode", () => {
  it("defaults to false when nothing is stored", () => {
    const { result } = renderHook(() => useAdvancedMode());
    expect(result.current[0]).toBe(false);
  });

  it("hydrates from localStorage", () => {
    window.localStorage.setItem(KEY, "1");
    const { result } = renderHook(() => useAdvancedMode());
    expect(result.current[0]).toBe(true);
  });

  it("persists changes to localStorage", () => {
    const { result } = renderHook(() => useAdvancedMode());
    act(() => result.current[1](true));
    expect(window.localStorage.getItem(KEY)).toBe("1");
    act(() => result.current[1](false));
    expect(window.localStorage.getItem(KEY)).toBe("0");
  });

  it("treats any non-1 stored value as basic mode", () => {
    window.localStorage.setItem(KEY, "yes");
    const { result } = renderHook(() => useAdvancedMode());
    expect(result.current[0]).toBe(false);
  });
});
