import { createHash } from "node:crypto";
import { PrivateViewerController } from "./controller.ts";
import type { ViewerClock } from "./controller.ts";
import type { PurgeReason, ViewerPorts, ViewerSource } from "./contracts.ts";

export const pdfBytes = new TextEncoder().encode(
  "%PDF-1.7\nunit fixture, never a rendered PDF acceptance substitute",
);
export const source: ViewerSource = {
  companyId: "company-1",
  userId: "user-1",
  sessionKey: "login-1",
  matterId: "matter-1",
  attachmentId: "file-1",
  filename: "source.pdf",
  contentType: "application/pdf",
  sizeBytes: pdfBytes.length,
  sha256: createHash("sha256").update(pdfBytes).digest("hex"),
};
export function deferred<T>() {
  let resolve!: (value: T) => void, reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
export class TestClock implements ViewerClock {
  time = 1000;
  private timers: { at: number; callback: () => void }[] = [];
  now = () => this.time;
  setTimeout = (callback: () => void, ms: number) => {
    const timer = { at: this.time + ms, callback };
    this.timers.push(timer);
    return timer;
  };
  clearTimeout = (timer: unknown) => {
    this.timers = this.timers.filter((item) => item !== timer);
  };
  advance(ms: number) {
    this.time += ms;
    const ready = this.timers.filter((timer) => timer.at <= this.time);
    this.timers = this.timers.filter((timer) => timer.at > this.time);
    for (const timer of ready) timer.callback();
  }
}
export async function settle() {
  for (let i = 0; i < 20; i++) await Promise.resolve();
}
export function fixture(
  overrides: Partial<ViewerPorts> = {},
  input = source,
  body = pdfBytes,
) {
  const calls: string[] = [],
    issued: Uint8Array[] = [];
  const clock = new TestClock();
  let invalidate: (reason: PurgeReason) => void = () => {};
  let unsubscribed = false;
  const ports: ViewerPorts = {
    revalidate: async (expected) => {
      calls.push("metadata");
      return { ...expected };
    },
    requestBytes: async (path, options) => {
      calls.push(`${options.rangeProbe ? "probe" : "body"}:${path}`);
      const bytes = options.rangeProbe ? body.slice(0, 1) : body.slice();
      issued.push(bytes);
      return {
        bytes,
        status: options.rangeProbe ? 206 : 200,
        contentType: input.contentType || "application/pdf",
        contentRange: options.rangeProbe
          ? `bytes 0-0/${input.sizeBytes}`
          : null,
        cacheControl: "private, no-store",
      };
    },
    sha256: async (bytes) => {
      calls.push("hash");
      return createHash("sha256").update(bytes).digest("hex");
    },
    subscribeInvalidation: (listener) => {
      invalidate = listener;
      return () => {
        unsubscribed = true;
      };
    },
    ...overrides,
  };
  const clear = deferred<void>();
  const controller = new PrivateViewerController(input, ports, clock, () => {
    calls.push("clear-visible");
    return clear.promise;
  });
  return {
    controller,
    ports,
    clock,
    calls,
    issued,
    clear,
    invalidate: (reason: PurgeReason) => invalidate(reason),
    isUnsubscribed: () => unsubscribed,
  };
}
