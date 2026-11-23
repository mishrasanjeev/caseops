// @vitest-environment node
import http, { type Server } from "node:http";
import type { AddressInfo } from "node:net";
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
    expect(rootManifest.overrides.undici).toBe("7.30.2");
    const copies = Object.entries(lock.packages).filter(([key]) => key.endsWith("/node_modules/undici") || key === "node_modules/undici");
    expect(copies.length).toBeGreaterThan(0);
    for (const [key, value] of copies) expect(value.version, key).toBe("7.30.2");
    expect(require("undici/package.json").version).toBe("7.30.2");
  });

  it("preserves ordinary cross-origin redirect header policy with tuple-array headers", async () => {
    // This explicitly exercises npm Undici, not Node's embedded fetch runtime.
    expect(require("undici/package.json").version).toBe("7.30.2");
    expect(require.resolve("undici")).toContain(`${path.sep}node_modules${path.sep}undici${path.sep}`);
    const { fetch } = require("undici") as typeof import("undici");
    expect(fetch).not.toBe(globalThis.fetch);
    const end = performance.now() + 4500, workEnd = end - 500;
    const rows: Array<{ route: string | undefined; marker: string | string[] | undefined; publicHeader: string | undefined }> = [];
    const servers: Server[] = [];
    const check = () => { if (performance.now() >= workEnd) throw new Error("PUBLIC_LOOPBACK_REDIRECT_BOUND"); };
    const listen = (server: Server) => new Promise<string>((resolve, reject) => {
      check(); servers.push(server);
      const timer = setTimeout(() => reject(new Error("PUBLIC_LOOPBACK_LISTEN_BOUND")), Math.min(1000, workEnd - performance.now()));
      server.once("error", error => { clearTimeout(timer); reject(error); });
      server.listen(0, "127.0.0.1", () => {
        clearTimeout(timer);
        try { check(); const address = server.address() as AddressInfo; expect(address.address).toBe("127.0.0.1"); resolve(`http://127.0.0.1:${address.port}`); }
        catch (error) { reject(error); }
      });
    });
    let caught = false, original: unknown;
    try {
      const destination = await listen(http.createServer((request, response) => {
        rows.push({ route: request.url, marker: request.headers["x-caseops-automated-test"], publicHeader: request.headers.authorization });
        response.writeHead(200, { "Content-Type": "text/plain" }); response.end("public-loopback-complete");
      }));
      const source = await listen(http.createServer((request, response) => {
        rows.push({ route: request.url, marker: request.headers["x-caseops-automated-test"], publicHeader: request.headers.authorization });
        response.writeHead(302, { Location: `${destination}/second` }); response.end();
      }));
      expect(source).not.toBe(destination); check();
      const response = await fetch(`${source}/first`, {
        redirect: "follow", signal: AbortSignal.timeout(Math.min(3000, Math.floor(workEnd - performance.now()))),
        // Fixed PUBLIC labels only. This is not a token, cookie or credential.
        headers: [["X-CaseOps-Automated-Test", "no-paid-providers"], ["Authorization", "CaseOps-PUBLIC-redirect-fixture"]],
      });
      check(); expect(response.status).toBe(200); expect(await response.text()).toBe("public-loopback-complete"); check();
      expect(rows).toEqual([
        { route: "/first", marker: "no-paid-providers", publicHeader: "CaseOps-PUBLIC-redirect-fixture" },
        { route: "/second", marker: "no-paid-providers", publicHeader: undefined },
      ]);
    } catch (error) { caught = true; original = error; }
    const cleanupErrors: unknown[] = [];
    for (const server of servers.reverse()) {
      try {
        server.closeAllConnections();
        await new Promise<void>((resolve, reject) => {
          const timer = setTimeout(() => reject(new Error("PUBLIC_LOOPBACK_CLOSE_BOUND")), Math.max(0, end - performance.now()));
          server.close(error => { clearTimeout(timer); if (error && (error as NodeJS.ErrnoException).code !== "ERR_SERVER_NOT_RUNNING") reject(error); else resolve(); });
        });
        expect(server.listening).toBe(false); expect(server.address()).toBeNull();
        if (performance.now() >= end) throw new Error("PUBLIC_LOOPBACK_FINAL_BOUND");
      } catch (error) { cleanupErrors.push(error); }
    }
    if (caught && cleanupErrors.length) throw new AggregateError([original, ...cleanupErrors], "PUBLIC_LOOPBACK_BODY_AND_CLEANUP");
    if (caught) throw original;
    if (cleanupErrors.length) throw new AggregateError(cleanupErrors, "PUBLIC_LOOPBACK_CLEANUP");
  });

  it("does not turn nested address comments into a different notification recipient", () => {
    const addressparser = require("nodemailer/lib/addressparser");
    expect(addressparser("Victim (x(y) <evil@example.net>) <v@example.org>"))
      .toEqual([{ address: "v@example.org", name: "Victim" }]);
  });
});
