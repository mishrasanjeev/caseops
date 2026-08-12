import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { canonicalJson } from "./canonical-json";

type GoldenFixture = {
  cases: Array<{
    name: string;
    value: unknown;
    canonical: string;
    sha256: string;
  }>;
};

const fixture = JSON.parse(
  readFileSync(
    resolve(process.cwd(), "../../tests/fixtures/idempotency_canonical_golden.json"),
    "utf8",
  ),
) as GoldenFixture;

describe("canonicalJson", () => {
  it.each(fixture.cases)("matches the shared $name fixture", ({ value, canonical, sha256 }) => {
    const encoded = canonicalJson(value);
    expect(encoded).toBe(canonical);
    expect(createHash("sha256").update(encoded, "utf8").digest("hex")).toBe(sha256);
  });

  it("rejects values that cannot round-trip across Python and JavaScript", () => {
    expect(() => canonicalJson({ amount: 1.5 })).toThrow(/safe integer/);
    expect(() => canonicalJson({ bad: "\ud800" })).toThrow(/unpaired surrogate/);
    expect(() => canonicalJson({ missing: undefined })).toThrow(/Unsupported/);
  });
});
