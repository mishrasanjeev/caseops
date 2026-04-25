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
    // AQ-002 (2026-04-25): default per-test timeout was 5000ms.
    // Form / dialog tests that type ~30+ characters with userEvent
    // sit under 2 s on a bare run but cross 5 s under v8 coverage
    // instrumentation on Linux runners (NewWorkspaceForm,
    // NewContractDialog, etc.). Bumping the floor to 15 s leaves
    // headroom without papering over real flakes — anything that
    // takes >15 s is genuinely broken, not just slow.
    testTimeout: 15_000,
    // Coverage config — v8 provider. Codex 2026-04-20 test-suite gap
    // audit asked for coverage tooling before we set thresholds.
    // Thresholds will be added once we have a baseline; for now the
    // config just enables `npm run test -- --coverage` locally and in
    // CI so the number is visible.
    coverage: {
      provider: "v8",
      // AQ-002 sub-item (2026-04-25): json-summary added so CI can
      // upload coverage-summary.json as an artifact and the gh-pages
      // / dashboard scrapers downstream can parse a stable shape.
      reporter: ["text", "html", "lcov", "json-summary"],
      reportsDirectory: "./coverage",
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
      // AQ-002 sub-item (2026-04-25): non-regression gate at today's
      // baseline minus a small buffer. Today: stmts 30.31% / branches
      // 22.89% / lines 31.83%. Floor here is rounded down so the
      // ordinary noise of a single unrelated edit can't trip CI, but
      // a real regression (e.g. deleting a tested module) will. Update
      // these in the SAME commit that lifts coverage; do NOT ratchet
      // down to make CI green.
      thresholds: {
        lines: 31,
        statements: 30,
        branches: 22,
      },
    },
  },
});
