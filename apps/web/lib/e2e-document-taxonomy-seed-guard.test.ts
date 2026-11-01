// @vitest-environment node

import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

// A browser journey that loads the document taxonomy through the admin seed
// endpoint never exercises the product provisioning path (workspace
// configuration, enablement, upload and the release backfill). That is how a
// tenant with an empty Classification select passed every journey. Journeys
// must rely on provisioning; only a deliberate contract test of the seed
// endpoint itself may call it, and it must say why here.
const ALLOWED_SEED_CALLERS: Record<string, string> = {
  "iplf-024a-document-foundation-2026-08-09.spec.ts":
    "API contract test of POST /api/ip/document-taxonomy/seed on a tenant with no IP workspace configuration (starts from an empty taxonomy and asserts the 14 seeded keys).",
};

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const e2eRoot = path.join(root, "tests", "e2e");
// Also catches a path split across string literals, e.g. "document-taxonomy" + "/seed".
const SEED_CALL = /document-taxonomy[`'"\s+]*\/seed\b|seedIpDocumentTaxonomy/;

function e2eSources(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    const full = path.join(directory, entry.name);
    if (entry.isDirectory()) return entry.name === "node_modules" ? [] : e2eSources(full);
    return /\.(ts|tsx|js|mjs|cjs)$/.test(entry.name) ? [full] : [];
  });
}

let scanned: { files: string[]; callers: Map<string, number[]> } | undefined;

// The tree lives on a synced drive; scan it once per run.
function scan() {
  if (scanned) return scanned;
  const files = e2eSources(e2eRoot);
  const callers = new Map<string, number[]>();
  for (const file of files) {
    const lines = readFileSync(file, "utf8").split(/\r?\n/);
    const hits = lines.flatMap((line, index) => (SEED_CALL.test(line) ? [index + 1] : []));
    if (hits.length) callers.set(path.relative(e2eRoot, file).replaceAll("\\", "/"), hits);
  }
  scanned = { files, callers };
  return scanned;
}

describe("e2e document taxonomy seed guard", { timeout: 60_000 }, () => {
  it("scans the real e2e tree", () => {
    expect(scan().files.length).toBeGreaterThan(100);
  });

  it("keeps the admin seed endpoint out of every e2e journey and support helper", () => {
    const offenders = [...scan().callers]
      .filter(([file]) => !(file in ALLOWED_SEED_CALLERS))
      .map(([file, lines]) => `tests/e2e/${file}:${lines.join(",")}`);
    expect(
      offenders,
      "Rely on IP workspace provisioning (assert it with support/ip-document-taxonomy.ts) instead of POST /api/ip/document-taxonomy/seed, or add a deliberate contract test to ALLOWED_SEED_CALLERS with a reason.",
    ).toEqual([]);
  });

  it("keeps every allowlist entry live and explained", () => {
    const { callers } = scan();
    for (const [file, reason] of Object.entries(ALLOWED_SEED_CALLERS)) {
      expect(callers.has(file), `${file} no longer calls the seed endpoint; drop it from the allowlist`).toBe(true);
      expect(reason.length).toBeGreaterThan(40);
    }
  });

  it("recognises the call shapes it guards against", () => {
    for (const sample of [
      'await api.post(`${apiBase}/api/ip/document-taxonomy/seed`, { headers })',
      'post(request, headers, "/api/ip/document-taxonomy/seed", {}, 200)',
      'api.post(base + "/api/ip/document-taxonomy" + "/seed")',
      "await seedIpDocumentTaxonomy()",
    ]) expect(SEED_CALL.test(sample), sample).toBe(true);
    for (const sample of [
      'api.get(`${apiBase}/api/ip/document-taxonomy`, { headers })',
      'api.put(`${apiBase}/api/ip/document-taxonomy/seeded_key`)',
    ]) expect(SEED_CALL.test(sample), sample).toBe(false);
  });
});
