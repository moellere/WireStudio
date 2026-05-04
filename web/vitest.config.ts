import { defineConfig, mergeConfig } from "vitest/config";
import viteConfig from "./vite.config";

export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: "jsdom",
      setupFiles: ["./src/test/setup.ts"],
      globals: false,
      // Existing pure-logic tests under src/lib don't need jsdom but the
      // overhead is negligible at this scale, so we keep one config.
      include: ["src/**/*.test.{ts,tsx}"],
    },
  }),
);
