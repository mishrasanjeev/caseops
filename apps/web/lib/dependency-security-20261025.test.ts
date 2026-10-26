import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const readJson = (file: string) => JSON.parse(readFileSync(path.join(root, file), "utf8"));
const manifest = readJson("apps/web/package.json");
const rootManifest = readJson("package.json");
const lock = readJson("package-lock.json") as {
  packages: Record<string, { version?: string; dependencies?: Record<string, string> }>;
};
const require = createRequire(path.join(root, "apps/web/package.json"));

describe("October25 security advisory closure (#559)", () => {
  for (const [name, version] of [["zod", "4.6.7"], ["nodemailer", "10.2.1"]]) {
    it(`pins reviewed ${name} in manifest, lock and every installed copy`, () => {
      expect(manifest.dependencies[name]).toBe(version);
      expect(lock.packages["apps/web"].dependencies?.[name]).toBe(version);
      const copies = Object.entries(lock.packages).filter(([key]) => key.endsWith(`/node_modules/${name}`) || key === `node_modules/${name}`);
      expect(copies.length).toBeGreaterThan(0);
      for (const [key, value] of copies) expect(value.version, key).toBe(version);
      expect(require(`${name}/package.json`).version).toBe(version);
    });
  }

  it("excludes every vulnerable undici copy while preserving the supported Node runtime", () => {
    expect(rootManifest.overrides.undici).toBe("7.30.1");
    const copies = Object.entries(lock.packages).filter(([key]) => key.endsWith("/node_modules/undici") || key === "node_modules/undici");
    expect(copies.length).toBeGreaterThan(0);
    for (const [key, value] of copies) expect(value.version, key).toBe("7.30.1");
    expect(require("undici/package.json").version).toBe("7.30.1");
  });

  it("does not turn nested address comments into a different notification recipient", () => {
    const addressparser = require("nodemailer/lib/addressparser");
    expect(addressparser("Victim (x(y) <evil@example.net>) <v@example.org>"))
      .toEqual([{ address: "v@example.org", name: "Victim" }]);
  });
});
