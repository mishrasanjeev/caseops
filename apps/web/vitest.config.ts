import path from "node:path";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "."),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    css: false,
    include: ["components/**/*.test.{ts,tsx}", "app/**/*.test.{ts,tsx}", "lib/**/*.test.{ts,tsx}"],
    // Coverage config — v8 provider. Codex 2026-04-20 test-suite gap
    // audit asked for coverage tooling before we set thresholds.
    // Thresholds will be added once we have a baseline; for now the
    // config just enables `npm run test -- --coverage` locally and in
    // CI so the number is visible.
    coverage: {
      provider: "v8",
      reporter: ["text", "html", "lcov"],
      include: ["app/**/*.{ts,tsx}", "components/**/*.{ts,tsx}", "lib/**/*.{ts,tsx}"],
      exclude: [
        "**/*.test.{ts,tsx}",
        "**/*.d.ts",
        "**/node_modules/**",
        "**/.next/**",
        "app/**/layout.tsx",
        "app/**/page.tsx",
        "lib/api/openapi-types.ts",
      ],
    },
  },
});
