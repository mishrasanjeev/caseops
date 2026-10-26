import test from "node:test";
import assert from "node:assert/strict";
import vm from "node:vm";
import { createRequire } from "node:module";
import { createViewerHtml } from "./html.ts";
import { rendererRuntimeSource } from "./generated/renderer-runtime-source.ts";
import { VIEWER_LIMITS } from "./contracts.ts";

const id = "a".repeat(32);
const require = createRequire(
  new URL("../../../web/package.json", import.meta.url),
);
const { chromium } = require("playwright") as typeof import("playwright");
type Chunk = { done: boolean; value?: { items: unknown[] } };
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
function reader(chunks: unknown[], pending = false, rejects = false) {
  const waiting = deferred<Chunk>();
  const counts = { reads: 0, cancels: 0, releases: 0 };
  return {
    counts,
    waiting,
    read() {
      counts.reads++;
      if (chunks.length)
        return Promise.resolve({ done: false, value: chunks.shift() });
      if (rejects) return Promise.reject(new Error("synthetic-read-failure"));
      return pending ? waiting.promise : Promise.resolve({ done: true });
    },
    cancel() {
      counts.cancels++;
      waiting.resolve({ done: true });
      return Promise.resolve();
    },
    releaseLock() {
      counts.releases++;
    },
  };
}
function start(
  readers: ReturnType<typeof reader>[],
  maxChars: number = VIEWER_LIMITS.maxPageTextCharacters,
) {
  const events: any[] = [],
    listeners: Record<string, (event?: any) => void> = {};
  const content = { hidden: true },
    text = { textContent: "" },
    status = { textContent: "" };
  let now = 0,
    streams = 0,
    legacyReads = 0;
  const page = {
    getViewport: () => ({ width: 100, height: 100 }),
    render: () => ({ promise: Promise.resolve() }),
    streamTextContent(options: unknown) {
      assert.equal(JSON.stringify(options), '{"disableNormalization":false}');
      const value = readers[streams++];
      assert.ok(value);
      return { getReader: () => value };
    },
    getTextContent() {
      legacyReads++;
      throw new TypeError("async iterator unavailable");
    },
    cleanup() {},
  };
  const window = {
    innerWidth: 402,
    devicePixelRatio: 2,
    pdfjsLib: {
      AnnotationMode: { DISABLE: 0 },
      getDocument: () => ({
        promise: Promise.resolve({
          numPages: 2,
          isPureXfa: false,
          getPage: () => Promise.resolve(page),
        }),
        destroy() {},
      }),
    },
    ReactNativeWebView: {
      postMessage: (value: string) => events.push(JSON.parse(value)),
    },
    addEventListener: (name: string, callback: (event?: any) => void) => {
      listeners[name] = callback;
    },
  };
  const nodes: Record<string, any> = {
    content,
    "page-text": text,
    status,
    page: { style: {}, getContext: () => ({}), setAttribute() {} },
  };
  const document = {
    hidden: false,
    getElementById: (name: string) => nodes[name],
    addEventListener: (name: string, callback: (event?: any) => void) => {
      listeners[name] = callback;
    },
  };
  const config = {
    id,
    limits: { ...VIEWER_LIMITS, maxPageTextCharacters: maxChars },
    assets: {},
  };
  vm.runInNewContext(`(${rendererRuntimeSource})(${JSON.stringify(config)});`, {
    window,
    document,
    Date: { now: () => now },
    setTimeout: () => 1,
    clearTimeout() {},
    atob: (value: string) => Buffer.from(value, "base64").toString("binary"),
  });
  const receive = (value: object) =>
    listeners.message({ data: JSON.stringify({ id, ...value }) });
  return {
    events,
    text,
    content,
    document,
    listeners,
    receive,
    elapsed: (value: number) => {
      now = value;
    },
    streams: () => streams,
    legacyReads: () => legacyReads,
  };
}
async function settle() {
  for (let n = 0; n < 30; n++) await Promise.resolve();
}
async function transfer(target: ReturnType<typeof start>) {
  target.receive({
    type: "begin",
    kind: "pdf",
    mime: "application/pdf",
    length: 1,
    ttl: 15000,
    page: 1,
    zoom: 1,
  });
  target.receive({ type: "chunk", sequence: 0, data: "QQ==" });
  target.receive({ type: "end" });
  await settle();
}
const pageEvents = (target: ReturnType<typeof start>) =>
  target.events.filter((event) => event.type === "page");

test("PDF text uses serial chunks without async iteration and releases its reader", async () => {
  const r = reader([
    {
      items: [{ str: "first", hasEOL: false }, { type: "beginMarkedContent" }],
    },
    { items: [{ str: "second", hasEOL: true }] },
  ]);
  const target = start([r]);
  await transfer(target);
  assert.equal(target.legacyReads(), 0);
  assert.equal(target.streams(), 1);
  assert.equal(target.text.textContent, "first second\n");
  assert.equal(target.content.hidden, false);
  assert.equal(pageEvents(target).length, 1);
  assert.deepEqual(r.counts, { reads: 3, cancels: 0, releases: 1 });
});
test("PDF text character overflow cancels and releases before any page acknowledgement", async () => {
  const r = reader([{ items: [{ str: "12345678" }] }]);
  const target = start([r], 8);
  await transfer(target);
  assert.equal(pageEvents(target).length, 0);
  assert.equal(target.text.textContent, "");
  assert.equal(target.events.at(-1).type, "error");
  assert.equal(r.counts.cancels, 1);
  assert.equal(r.counts.releases, 1);
});
test("purge cancels a pending text read and cannot reveal its earlier chunks", async () => {
  const r = reader([{ items: [{ str: "private synthetic text" }] }], true);
  const target = start([r]);
  await transfer(target);
  assert.equal(r.counts.reads, 2);
  target.receive({ type: "purge" });
  await settle();
  assert.equal(target.text.textContent, "");
  assert.equal(target.content.hidden, true);
  assert.equal(pageEvents(target).length, 0);
  assert.deepEqual(r.counts, { reads: 2, cancels: 1, releases: 1 });
});
test("lease expiry during a pending text read clears and releases without page acknowledgement", async () => {
  const r = reader([], true);
  const target = start([r]);
  await transfer(target);
  target.elapsed(15001);
  r.waiting.resolve({ done: true });
  await settle();
  assert.equal(pageEvents(target).length, 0);
  assert.equal(target.text.textContent, "");
  assert.equal(target.content.hidden, true);
  assert.equal(r.counts.cancels, 1);
  assert.equal(r.counts.releases, 1);
});
test("superseded page text cancels once and only the new page can acknowledge", async () => {
  const old = reader([{ items: [{ str: "old page" }] }], true),
    current = reader([{ items: [{ str: "new page" }] }]);
  const target = start([old, current]);
  await transfer(target);
  target.receive({ type: "navigate", page: 2, zoom: 1 });
  await settle();
  assert.equal(target.text.textContent, "new page ");
  assert.deepEqual(
    pageEvents(target).map((event) => event.page),
    [2],
  );
  assert.equal(old.counts.cancels, 1);
  assert.equal(old.counts.releases, 1);
  assert.equal(current.counts.cancels, 0);
  assert.equal(current.counts.releases, 1);
});
test("failed text read retains an error and cancels/releases its incomplete stream", async () => {
  const r = reader([{ items: [{ str: "partial" }] }], false, true);
  const target = start([r]);
  await transfer(target);
  assert.equal(target.events.at(-1).type, "error");
  assert.equal(pageEvents(target).length, 0);
  assert.equal(target.text.textContent, "");
  assert.equal(r.counts.cancels, 1);
  assert.equal(r.counts.releases, 1);
});
test("malformed text chunks and finite empty-chunk exhaustion cannot pass", async () => {
  for (const chunks of [
    [{ items: null }],
    Array.from({ length: 6 }, () => ({ items: [] })),
  ]) {
    const r = reader(chunks);
    const target = start([r], 3);
    await transfer(target);
    assert.equal(target.events.at(-1).type, "error");
    assert.equal(pageEvents(target).length, 0);
    assert.equal(r.counts.cancels, 1);
    assert.equal(r.counts.releases, 1);
    assert.ok(r.counts.reads <= 4);
  }
});
test("a rejected cancel cannot replace the original text failure or retain the reader", async () => {
  const r = reader([{ items: null }]);
  r.cancel = () => {
    r.counts.cancels++;
    return Promise.reject(new Error("synthetic-cancel-failure"));
  };
  const target = start([r]);
  await transfer(target);
  assert.equal(target.events.at(-1).type, "error");
  assert.equal(pageEvents(target).length, 0);
  assert.equal(r.counts.cancels, 1);
  assert.equal(r.counts.releases, 1);
  assert.equal(target.text.textContent, "");
});
test("a release failure rejects visible completion and cancels the retained reader", async () => {
  const r = reader([{ items: [{ str: "synthetic" }] }]);
  r.releaseLock = () => {
    r.counts.releases++;
    if (r.counts.releases === 1) throw new Error("synthetic-release-failure");
  };
  const target = start([r]);
  await transfer(target);
  assert.equal(target.events.at(-1).type, "error");
  assert.equal(pageEvents(target).length, 0);
  assert.equal(r.counts.cancels, 1);
  assert.equal(r.counts.releases, 2);
  assert.equal(target.text.textContent, "");
});
test("pending cancellation releases after settlement while purge clears text immediately", async () => {
  const r = reader([{ items: [{ str: "synthetic" }] }], true),
    cancelled = deferred<void>();
  let settled = false;
  r.cancel = () => {
    r.counts.cancels++;
    return cancelled.promise;
  };
  r.releaseLock = () => {
    r.counts.releases++;
    if (!settled) throw new Error("synthetic-pending-read");
  };
  const target = start([r]);
  await transfer(target);
  target.receive({ type: "purge" });
  assert.equal(target.text.textContent, "");
  assert.equal(target.content.hidden, true);
  assert.equal(r.counts.cancels, 1);
  settled = true;
  cancelled.resolve();
  r.waiting.resolve({ done: true });
  await settle();
  assert.equal(pageEvents(target).length, 0);
  assert.equal(r.counts.cancels, 1);
  assert.equal(r.counts.releases, 2);
});

function publicPdf() {
  const content = (value: string) => {
    const stream = `BT /F1 20 Tf 20 200 Td (${value}) Tj ET`;
    return `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`;
  };
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 400] /Resources << /Font << /F1 7 0 R >> >> /Contents 4 0 R >>",
    content("Portable page one"),
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 400] /Resources << /Font << /F1 7 0 R >> >> /Contents 6 0 R >>",
    content("Portable page two"),
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
  ];
  let value = "%PDF-1.7\n";
  const offsets = [0];
  for (const [index, object] of objects.entries()) {
    offsets.push(value.length);
    value += `${index + 1} 0 obj\n${object}\nendobj\n`;
  }
  const xref = value.length;
  value += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n${offsets
    .slice(1)
    .map((offset) => `${String(offset).padStart(10, "0")} 00000 n \n`)
    .join(
      "",
    )}trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(value);
}
test("actual PDF.js browser program renders both pages when ReadableStream has no asyncIterator", async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({
      viewport: { width: 402, height: 874 },
    });
    await page.route("**/*", (route) => route.abort());
    await page.evaluate(() => {
      Object.defineProperty(ReadableStream.prototype, Symbol.asyncIterator, {
        value: undefined,
        configurable: true,
      });
      (window as any).__events = [];
      (window as any).ReactNativeWebView = {
        postMessage: (value: string) =>
          (window as any).__events.push(JSON.parse(value)),
      };
    });
    await page.setContent(createViewerHtml(id));
    await page.waitForFunction(() =>
      (window as any).__events.some((event: any) => event.type === "ready"),
    );
    const bytes = publicPdf();
    const supplierFailure = await page.evaluate(
      async (data: number[]) => {
        const task = (window as any).pdfjsLib.getDocument({
          data: new Uint8Array(data),
          useWorkerFetch: false,
          useSystemFonts: false,
          disableFontFace: true,
          useWasm: false,
        });
        const doc = await task.promise;
        try {
          await (await doc.getPage(1)).getTextContent();
          return "unexpected-success";
        } catch (error) {
          return (error as Error).name;
        } finally {
          await task.destroy();
        }
      },
      [...bytes],
    );
    assert.equal(supplierFailure, "TypeError");
    const send = (message: object) =>
      page.evaluate(
        (value) =>
          window.dispatchEvent(new MessageEvent("message", { data: value })),
        JSON.stringify({ id, ...message }),
      );
    await send({
      type: "begin",
      kind: "pdf",
      mime: "application/pdf",
      length: bytes.length,
      ttl: 15000,
      page: 1,
      zoom: 1,
    });
    await send({ type: "chunk", sequence: 0, data: bytes.toString("base64") });
    await send({ type: "end" });
    await page.waitForFunction(() =>
      (window as any).__events.some(
        (event: any) => event.type === "page" || event.type === "error",
      ),
    );
    const first = await page.evaluate(() => ({
      events: (window as any).__events,
      text: document.getElementById("page-text")!.textContent,
    }));
    assert.ok(
      first.events.some(
        (event: any) =>
          event.type === "page" && event.page === 1 && event.pages === 2,
      ),
      JSON.stringify(first.events),
    );
    assert.match(first.text || "", /Portable page one/);
    await send({ type: "navigate", page: 2, zoom: 1 });
    await page.waitForFunction(() =>
      (window as any).__events.some(
        (event: any) => event.type === "page" && event.page === 2,
      ),
    );
    assert.match(
      await page.locator("#page-text").innerText(),
      /Portable page two/,
    );
    assert.equal(
      await page.evaluate(
        () => typeof (ReadableStream.prototype as any)[Symbol.asyncIterator],
      ),
      "undefined",
    );
  } finally {
    await browser.close();
  }
});
