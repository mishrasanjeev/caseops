// @vitest-environment node

import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

// Journeys name the records they write after their run id, and production
// tenants retain every run. A UUID run id therefore leaves records whose names
// read as leaked internal ids to every later screen check: on 2026-11-03,
// retained "IP18 <uuid> missing 50" docket titles failed BUG-014's hit-screen
// check. Journeys use runId() from support/run-id.ts; only a loopback-only
// fixture whose own seeding contract takes a UUID may keep one, and says why.
const ALLOWED_UUID_RUNS: Record<string, string> = {
  "platform-leads-2026-10-21.spec.ts":
    "Loopback-only console journey (never runs against production); its local fixture endpoint is keyed by the run id.",
  "ram-2026-10-22-drafting.spec.ts":
    "Loopback-only journey on its own freshly bootstrapped tenant; support/ram_batch3_draft_fixture.py requires a UUID run.",
};

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const e2eRoot = path.join(root, "tests", "e2e");
const UUID_RUN = /\brun\s*[=:]\s*(?:crypto\.)?randomUUID\(\)\s*[;,}]/;

function e2eSources(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    const full = path.join(directory, entry.name);
    if (entry.isDirectory()) return entry.name === "node_modules" ? [] : e2eSources(full);
    return /\.(ts|tsx|js|mjs|cjs)$/.test(entry.name) ? [full] : [];
  });
}

describe("e2e run ids", () => {
  it("never name retained records with a UUID run id", () => {
    const offenders = e2eSources(e2eRoot)
      .map(file => path.relative(e2eRoot, file).replaceAll("\\", "/"))
      .filter(file => UUID_RUN.test(readFileSync(path.join(e2eRoot, file), "utf8")));
    expect(offenders.filter(file => !(file in ALLOWED_UUID_RUNS))).toEqual([]);
    expect(Object.keys(ALLOWED_UUID_RUNS).filter(file => !offenders.includes(file))).toEqual([]);
  });

  it("makes run ids that are unique, slug-safe and never UUID-shaped", async () => {
    const { RUN_ID, runId } = await import("../../../tests/e2e/support/run-id");
    const ids = Array.from({ length: 20 }, () => runId());
    expect(new Set(ids).size).toBe(ids.length);
    for (const id of ids) {
      expect(id).toMatch(RUN_ID);
      expect(id).not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/);
    }
  });
});
