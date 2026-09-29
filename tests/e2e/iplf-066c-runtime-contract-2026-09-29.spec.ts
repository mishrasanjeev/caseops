import { execFileSync } from "node:child_process";

import { expect, test } from "@playwright/test";

import { e2eEnv, repoRoot, resolveE2EReleaseSha } from "./support/env";

test("IPLF-066C standard local servers receive the actual candidate identity", () => {
  const expected = process.env.CASEOPS_RELEASE_SHA?.trim().toLowerCase() ||
    execFileSync("git", ["rev-parse", "HEAD"], {
      cwd: repoRoot, encoding: "utf8", timeout: 5_000,
    }).trim();
  expect(e2eEnv.CASEOPS_RELEASE_SHA).toBe(expected);
  expect(e2eEnv.CASEOPS_RELEASE_SHA).toMatch(/^[0-9a-f]{40}$/);
});

test("IPLF-066C explicit Docker identity wins without reading Git", () => {
  const sha = "AB".repeat(20);
  expect(resolveE2EReleaseSha(` ${sha}\n`, () => {
    throw new Error("Git must not override the explicit image identity");
  })).toBe(sha.toLowerCase());
});

test("IPLF-066C absent identity resolves the candidate checkout", () => {
  expect(resolveE2EReleaseSha(undefined, () => `${"cd".repeat(20)}\n`))
    .toBe("cd".repeat(20));
});

for (const invalid of ["", "main", "fb3e3454", "g".repeat(40)]) {
  test(`IPLF-066C invalid explicit identity fails closed: ${JSON.stringify(invalid)}`, () => {
    let reads = 0;
    expect(() => resolveE2EReleaseSha(invalid, () => {
      reads += 1;
      return "ab".repeat(20);
    })).toThrow("exact 40-character Git SHA");
    expect(reads).toBe(0);
  });
}

test("IPLF-066C invalid Git identity fails closed", () => {
  expect(() => resolveE2EReleaseSha(undefined, () => "unavailable"))
    .toThrow("exact 40-character Git SHA");
});

test("IPLF-066C missing Git evidence is not replaced with synthetic identity", () => {
  expect(() => resolveE2EReleaseSha(undefined, () => {
    throw new Error("candidate Git lookup failed");
  })).toThrow("candidate Git lookup failed");
});
