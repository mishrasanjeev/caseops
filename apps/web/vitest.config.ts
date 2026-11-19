import path from "node:path";

import react from "@vitejs/plugin-react";
import { configDefaults, defineConfig } from "vitest/config";

import { hostTrustedForks } from "./lib/vitest-host-pool";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "."),
    },
  },
  test: {
    pool: hostTrustedForks,
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    css: false,
    // Bound coverage fan-out without extending child collection or UI deadlines.
    maxWorkers: 2,
    // Native Playwright discovery owns its bounded cold-collection interval.
    // Run that complete source oracle before competing coverage workers;
    // the constructor's 15s/8s limits and every inventory assertion stay fixed.
    projects: [
      {
        extends: true,
        test: {
          name: "source-inventory",
          include: ["lib/prod-tester-source-inventory.test.ts"],
          fileParallelism: false,
          // Vitest4.1.12 appends isolated single-worker order0 files last.
          // A positive order keeps this complete oracle ahead of coverage.
          sequence: { groupOrder: 1 },
        },
      },
      {
        extends: true,
        test: {
          name: "web",
          include: ["components/**/*.test.{ts,tsx}", "app/**/*.test.{ts,tsx}", "lib/**/*.test.{ts,tsx}"],
          exclude: [...configDefaults.exclude, "lib/prod-tester-source-inventory.test.ts"],
          sequence: { groupOrder: 2 },
        },
      },
    ],
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
      // 2026-04-28 ratchet — full coverage run produced lines 35.66 %,
      // stmts 33.99 %, branches 26.46 % (188 tests, all green; was
      // 141/142 with 1 timeout in the 2026-04-25 audit). Threshold set
      // ~1 pp below to leave room for unrelated-edit noise. Lift these
      // in the SAME commit that adds new tests; never ratchet down to
      // make CI green.
      thresholds: {
        lines: 34,
        statements: 32,
        branches: 25,
      },
    },
  },
});
