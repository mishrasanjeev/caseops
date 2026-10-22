import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const manifest = JSON.parse(readFileSync(path.join(root, "apps/web/package.json"), "utf8"));
const lock = JSON.parse(readFileSync(path.join(root, "package-lock.json"), "utf8")) as {
  packages: Record<string, { version?: string; dependencies?: Record<string, string>; devDependencies?: Record<string, string> }>;
};

// Reviewed stable releases fixing the October22 Next and Vitest advisories.
const nextVersion = "16.4.2";
const vitestVersion = "4.1.12";

describe("October23 dependency security baseline", () => {
  it("pins the reviewed Next release in both workspace manifests", () => {
    expect(manifest.dependencies.next).toBe(nextVersion);
    expect(lock.packages["apps/web"].dependencies?.next).toBe(nextVersion);
  });

  it("ships only the reviewed Next runtime and matching native compiler packages", () => {
    const entries = Object.entries(lock.packages).filter(([key]) =>
      /(?:^|\/)node_modules\/(?:next|@next\/env|@next\/swc-[^/]+)$/.test(key),
    );
    expect(entries.length).toBeGreaterThan(2);
    expect(lock.packages["node_modules/next"].version).toBe(nextVersion);
    for (const [key, entry] of entries) expect(entry.version, key).toBe(nextVersion);
  });

  it("pins matching patched Vitest and coverage releases", () => {
    for (const name of ["vitest", "@vitest/coverage-v8"]) {
      expect(manifest.devDependencies[name], name).toBe(vitestVersion);
      expect(lock.packages["apps/web"].devDependencies?.[name], name).toBe(vitestVersion);
    }
  });

  it("does not retain an older nested Vitest mocker or coverage runtime", () => {
    const entries = Object.entries(lock.packages).filter(([key]) =>
      /(?:^|\/)node_modules\/(?:vitest|@vitest\/[^/]+)$/.test(key),
    );
    expect(entries.length).toBeGreaterThan(3);
    expect(lock.packages["node_modules/@vitest/mocker"].version).toBe(vitestVersion);
    for (const [key, entry] of entries) expect(entry.version, key).toBe(vitestVersion);
  });
});
