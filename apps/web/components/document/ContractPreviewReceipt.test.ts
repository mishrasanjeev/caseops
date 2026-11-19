// @vitest-environment node
import { createHash, webcrypto } from "node:crypto";
import { lstatSync, realpathSync } from "node:fs";
import os from "node:os";
import path from "node:path";

import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { installContractPreviewReceipt, type ContractPreviewReceipt } from "../../../../tests/e2e/support/bugs5_contract_reported_20261111";

const bytes = new TextEncoder().encode("%PDF-1.7\nSynthetic observer fixture\n");
const digest = createHash("sha256").update(bytes).digest("hex");
const binding = { origin: "http://127.0.0.1:47199", pathname: "/api/contracts/11111111-1111-4111-8111-111111111111/attachments/22222222-2222-4222-8222-222222222222/preview", maxBytes: bytes.length };
const url = binding.origin + binding.pathname;
const receipt = () => (window as unknown as { __caseopsContractPreview: { receipt: ContractPreviewReceipt } }).__caseopsContractPreview.receipt;
let original: ReturnType<typeof vi.fn>;

beforeEach(() => {
  original = vi.fn();
  vi.stubGlobal("window", { fetch: original });
  vi.stubGlobal("location", { href: binding.origin + "/" });
  vi.stubGlobal("crypto", webcrypto);
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

function response(data: Uint8Array = bytes) {
  return new Response(new ReadableStream<Uint8Array>({ start(controller) {
    controller.enqueue(data.slice(0, 5)); controller.enqueue(data.slice(5)); controller.close();
  } }), { headers: { "content-type": "application/pdf" } });
}

it("observes the same streamed fetch, preserves caller arguments and application bytes, and retains only scalar digest metadata", async () => {
  original.mockImplementation(() => Promise.resolve(response()));
  installContractPreviewReceipt(binding);
  const init = { headers: { Authorization: "Bearer synthetic-only", "X-CaseOps-Automated-Test": "no-paid-providers" }, credentials: "include" as const };
  const received = await window.fetch(url, init);
  expect(new Uint8Array(await received.arrayBuffer())).toEqual(bytes);
  await vi.waitFor(() => expect(receipt().status).toBe("complete"));
  expect(original.mock.calls).toEqual([[url, init]]);
  expect(receipt()).toEqual({ status: "complete", requests: 1, bytes: bytes.length, sha256: digest, mime: "application/pdf", failure: "none" });
  expect(JSON.stringify(receipt())).not.toContain("Synthetic observer fixture");
  expect(JSON.stringify(receipt())).not.toContain("Bearer");
});

it("keeps a wrong source digest distinguishable rather than using a separate successful GET", async () => {
  const changed = new Uint8Array(bytes); changed[changed.length - 2] ^= 1;
  original.mockImplementation(() => Promise.resolve(response(changed)));
  installContractPreviewReceipt(binding);
  expect(new Uint8Array(await (await window.fetch(url)).arrayBuffer())).toEqual(changed);
  await vi.waitFor(() => expect(receipt().status).toBe("complete"));
  expect(receipt().bytes).toBe(bytes.length);
  expect(receipt().sha256 === digest).toBe(false);
  expect(original).toHaveBeenCalledTimes(1);
});

const inadmissibleResponses: ResponseInit[] = [
  { status: 403, headers: { "content-type": "application/pdf" } },
  { status: 200, headers: { "content-type": "text/plain" } },
  { status: 200, headers: { "content-type": "application/pdf", "content-length": String(bytes.length + 1) } },
];
it.each(inadmissibleResponses)("refuses an inadmissible response without consuming or replacing the application's response", async init => {
  original.mockImplementation(() => Promise.resolve(new Response(bytes, init)));
  installContractPreviewReceipt(binding);
  const received = await window.fetch(url);
  expect(new Uint8Array(await received.arrayBuffer())).toEqual(bytes);
  expect(receipt().status).toBe("failed");
  expect(receipt().failure).toBe("admission");
  expect(receipt().sha256).toBeNull();
  expect(original).toHaveBeenCalledTimes(1);
});

it("bounds the actual cloned stream even without content-length, preserving the original stream", async () => {
  const larger = new Uint8Array(bytes.length + 1); larger.set(bytes); larger[larger.length - 1] = 9;
  original.mockImplementation(() => Promise.resolve(response(larger)));
  installContractPreviewReceipt(binding);
  expect(new Uint8Array(await (await window.fetch(url)).arrayBuffer())).toEqual(larger);
  await vi.waitFor(() => expect(receipt().status).toBe("failed"));
  expect(receipt().failure).toBe("oversize");
  expect(receipt().sha256).toBeNull();
  expect(original).toHaveBeenCalledTimes(1);
});

it("fails duplicate preview admission instead of hiding an extra application request", async () => {
  original.mockImplementation(() => Promise.resolve(response()));
  installContractPreviewReceipt(binding);
  await (await window.fetch(url)).arrayBuffer();
  await vi.waitFor(() => expect(receipt().status).toBe("complete"));
  await (await window.fetch(url)).arrayBuffer();
  expect(receipt().status).toBe("failed");
  expect(receipt().failure).toBe("duplicate");
  expect(receipt().requests).toBe(2);
  expect(original).toHaveBeenCalledTimes(2);
});

it("keeps a duplicate refusal latched when the first fetch resolves after the second", async () => {
  let finishFirst!: (value: Response) => void;
  original.mockImplementationOnce(() => new Promise<Response>(resolve => { finishFirst = resolve; }))
    .mockImplementationOnce(() => Promise.resolve(response()));
  installContractPreviewReceipt(binding);
  const first = window.fetch(url);
  await (await window.fetch(url)).arrayBuffer();
  expect(receipt().failure).toBe("duplicate");
  finishFirst(response());
  expect(new Uint8Array(await (await first).arrayBuffer())).toEqual(bytes);
  await vi.waitFor(() => expect(receipt().status).not.toBe("reading"));
  expect(receipt().status).toBe("failed");
  expect(receipt().failure).toBe("duplicate");
  expect(receipt().sha256).toBeNull();
  expect(receipt().requests).toBe(2);
  expect(original).toHaveBeenCalledTimes(2);
});

it("retains a stream failure separately from a successful digest", async () => {
  original.mockImplementation(() => Promise.resolve(new Response(new ReadableStream({ start(controller) {
    controller.error(new Error("Synthetic stream refusal"));
  } }), { headers: { "content-type": "application/pdf" } })));
  installContractPreviewReceipt(binding);
  const received = await window.fetch(url);
  await expect(received.arrayBuffer()).rejects.toThrow("Synthetic stream refusal");
  await vi.waitFor(() => expect(receipt().status).toBe("failed"));
  expect(receipt().failure).toBe("stream");
  expect(receipt().sha256).toBeNull();
});

it("ends the observer at ten seconds without cancelling the application's body", async () => {
  vi.useFakeTimers();
  let source!: ReadableStreamDefaultController<Uint8Array>;
  original.mockImplementation(() => Promise.resolve(new Response(new ReadableStream<Uint8Array>({ start(controller) { source = controller; } }), { headers: { "content-type": "application/pdf" } })));
  installContractPreviewReceipt(binding);
  const received = await window.fetch(url);
  await vi.advanceTimersByTimeAsync(9_999);
  expect(receipt().status).toBe("reading");
  await vi.advanceTimersByTimeAsync(1);
  expect(receipt().status).toBe("failed");
  expect(receipt().failure).toBe("deadline");
  source.enqueue(bytes); source.close();
  expect(new Uint8Array(await received.arrayBuffer())).toEqual(bytes);
  await Promise.resolve();
  expect(receipt().sha256).toBeNull();
  expect(vi.getTimerCount()).toBe(0);
});

it.each([url + "?other=1", url + "/different", "https://other.example" + binding.pathname])("does not observe a different request or make a replacement fetch", async other => {
  original.mockImplementation(() => Promise.resolve(response()));
  installContractPreviewReceipt(binding);
  await (await window.fetch(other)).arrayBuffer();
  expect(receipt().status).toBe("waiting");
  expect(receipt().requests).toBe(0);
  expect(original).toHaveBeenCalledTimes(1);
});

it("keeps one exact binding and rejects unsafe or oversized observation setup", () => {
  expect(() => installContractPreviewReceipt({ ...binding, origin: "https://other.example" })).toThrow();
  expect(() => installContractPreviewReceipt({ ...binding, maxBytes: 32 * 1024 * 1024 + 1 })).toThrow();
  installContractPreviewReceipt(binding);
  const fetch = window.fetch;
  installContractPreviewReceipt(binding);
  expect(window.fetch).toBe(fetch);
  expect(() => installContractPreviewReceipt({ ...binding, maxBytes: bytes.length - 1 })).toThrow();
  expect(original).not.toHaveBeenCalled();
});

it("proves the observer in an offline browser, including transport-injected headers and wrong-source bytes", async () => {
  vi.unstubAllGlobals();
  const { chromium } = await import("@playwright/test");
  // The public server API owns its temporary profile and exposes the native child.
  const server = await chromium.launchServer({ headless: true, timeout: 5_000 });
  const child = server.process();
  let ownedProfile: string | undefined;
  let sourceChanged = false;
  const received: string[] = [];
  try {
    expect(child.pid).toBeGreaterThan(0);
    expect(child.exitCode).toBeNull();
    const profiles = child.spawnargs.filter(arg => arg.startsWith("--user-data-dir="));
    expect(profiles).toHaveLength(1);
    const profile = profiles[0].slice("--user-data-dir=".length);
    const root = realpathSync(os.tmpdir());
    const resolved = realpathSync(profile);
    const relative = path.relative(root, resolved);
    expect(relative).not.toMatch(/^\.\.(?:[\\/]|$)/);
    expect(path.isAbsolute(relative)).toBe(false);
    expect(path.basename(resolved)).toMatch(/^playwright_chromiumdev_profile-/);
    expect(lstatSync(profile).isSymbolicLink()).toBe(false);
    ownedProfile = resolved;
    const browser = await chromium.connect(server.wsEndpoint(), {
      timeout: 5_000, headers: { "X-CaseOps-Automated-Test": "no-paid-providers" },
    });
    const context = await browser.newContext({
      offline: true, serviceWorkers: "block",
      extraHTTPHeaders: { "X-CaseOps-Automated-Test": "no-paid-providers" },
    });
    await context.route("**/*", async route => {
      const request = route.request(), target = new URL(request.url());
      if (target.origin !== binding.origin || request.method() !== "GET") return route.abort("blockedbyclient");
      expect(request.headers()["x-caseops-automated-test"]).toBe("no-paid-providers");
      if (target.pathname === "/") return route.fulfill({ contentType: "text/html", body: "<!doctype html><title>Owned offline observer control</title>" });
      if (target.pathname !== binding.pathname) return route.abort("blockedbyclient");
      received.push(request.headers()["x-caseops-automated-test"]);
      const body = Buffer.from(bytes);
      if (sourceChanged) body[body.length - 2] ^= 1;
      return route.fulfill({ contentType: "application/pdf", body });
    });
    const page = await context.newPage();
    await page.goto(binding.origin, { timeout: 5_000 });
    for (const changed of [false, true]) {
      sourceChanged = changed;
      if (changed) await page.reload({ timeout: 5_000 });
      await page.evaluate(installContractPreviewReceipt, binding);
      // The real constructor receives the marker from its context, not fetch init.
      const appBytes = await page.evaluate(async target => Array.from(new Uint8Array(await (await fetch(target)).arrayBuffer())), url);
      const expectedBytes = Array.from(bytes);
      if (changed) expectedBytes[expectedBytes.length - 2] ^= 1;
      expect(appBytes).toEqual(expectedBytes);
      await vi.waitFor(async () => expect(await page.evaluate(() => (window as unknown as {
        __caseopsContractPreview: { receipt: ContractPreviewReceipt };
      }).__caseopsContractPreview.receipt.status)).toBe("complete"));
      const observed = await page.evaluate(() => (window as unknown as {
        __caseopsContractPreview: { receipt: ContractPreviewReceipt };
      }).__caseopsContractPreview.receipt);
      expect(observed.requests).toBe(1);
      expect(observed.bytes).toBe(bytes.length);
      expect(observed.sha256 === digest).toBe(!changed);
    }
    expect(received).toEqual(["no-paid-providers", "no-paid-providers"]);
  } finally {
    await server.close();
    expect(child.exitCode, "Owned native browser has actually exited").toBe(0);
    if (ownedProfile) {
      let absent = false;
      try { lstatSync(ownedProfile); }
      catch (error) {
        if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
        absent = true;
      }
      expect(absent, "Owned temporary browser profile is absent").toBe(true);
    }
  }
});
