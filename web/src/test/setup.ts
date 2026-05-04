/**
 * Vitest global setup. Imported once per test file via vitest.config.ts.
 *
 * Brings in @testing-library/jest-dom matchers (toBeInTheDocument,
 * toHaveClass, etc.) and a jsdom shim for the few browser APIs the
 * components touch but jsdom doesn't ship.
 */
import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// Unmount any rendered tree between tests so DOM queries from one
// test never leak into the next.
afterEach(() => {
  cleanup();
});
